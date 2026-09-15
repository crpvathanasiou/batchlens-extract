# AWS setup, operation and teardown

This guide deploys one **development** environment for the document-conversion slice. CloudFormation and the application are supplied; deployment, container execution and real-document acceptance must be demonstrated in your account. See `VERIFICATION.md` at the project root for the actual local evidence.

Do not execute cloud mutations or process a document until you have reviewed the templates, account, region, costs and sample and explicitly authorized that operation. No AWS mutation was performed while producing this package.

## 1. Prerequisites and values

You need Windows PowerShell, Git, Python **3.11**, Poetry, AWS CLI v2 and Docker Desktop with Linux containers. The commands below run from the project root, one command per line, without PowerShell backtick continuations. Replace uppercase placeholders. Use a dedicated development AWS profile with short-lived credentials, preferably AWS IAM Identity Center.

**Before deployment:** obtain a controlled DNS name such as `documents.example.com` and an **ISSUED ACM certificate in the selected region** covering that name. You must be able to create a DNS CNAME (or Route 53 alias) to the ALB. These templates do not buy a domain, request a certificate, create email invitations or configure enterprise identity federation. Without these prerequisites, run the offline example locally. A localhost HTTP test is not a public confidential-document service.

Operator permissions are required to review/create/update/delete the two CloudFormation stacks and their ECR, VPC/subnets/routes/IGW/endpoints/security groups, ALB/listener/target group, ECS/Fargate, S3, DynamoDB, SQS, CloudWatch Logs/alarms, Cognito and IAM resources; also `iam:PassRole` for the created task roles. Use a deployment role approved by your account administrator, not task-role credentials. Creating the test user needs `cognito-idp:AdminCreateUser` and `AdminSetUserPassword`. Read-only inspection needs the corresponding Describe/List/Get APIs and Service Quotas access. No policy for unrestricted account administration is supplied.

```powershell
$env:AWS_PROFILE = "YOUR_DEV_PROFILE"
$Region = "eu-west-1"
$env:AWS_DEFAULT_REGION = $Region
$Prefix = "batchlens-doc-dev"
$Domain = "documents.YOUR_DOMAIN"
$CertificateArn = "arn:aws:acm:REGION:ACCOUNT:certificate/YOUR_CERTIFICATE_ID"
$AllowedCidr = "YOUR_PUBLIC_IPV4/32"
$ImageTag = "doc-slice-001"
aws --version
python --version
poetry --version
docker version
aws sts get-caller-identity
aws acm describe-certificate --certificate-arn $CertificateArn --region $Region --query 'Certificate.{Status:Status,Names:SubjectAlternativeNames}'
```

Success: Python is 3.11, Docker has a running Linux server, AWS reports the intended account/role, the certificate is ISSUED and covers `$Domain`. The example region is a substitution, not a requirement or a statement about your previous buckets. Do not point this setup at unrelated existing resources.

Check current service/feature availability and your account's **regional** Textract Start/Get TPS and asynchronous analysis concurrency. TABLES and LAYOUT are used; there is no LLM/model selection or Bedrock model-access prerequisite in this slice.

```powershell
aws service-quotas list-service-quotas --service-code textract --region $Region --query 'Quotas[].{Name:QuotaName,Value:Value,Code:QuotaCode}' --output table
aws service-quotas list-aws-default-service-quotas --service-code textract --region $Region --query 'Quotas[].{Name:QuotaName,Value:Value,Code:QuotaCode}' --output table
```

Review [Textract endpoints and regional quotas](https://docs.aws.amazon.com/general/latest/gr/textract.html), [Textract quota types](https://docs.aws.amazon.com/textract/latest/dg/limits-quotas-explained.html) and [feature request options](https://docs.aws.amazon.com/textract/latest/APIReference/API_StartDocumentAnalysis.html). If the account quota list is incomplete, use the Service Quotas console in that region. Start with `ActiveJobs=2` only if at least two concurrent analysis jobs are available after accounting for other applications. SDK throttling retries do not reserve capacity in your account.

## 2. Local gate and review

```powershell
poetry env use 3.11
poetry install
poetry run ruff check .
poetry run ruff format --check .
poetry run pyright
poetry run pytest
poetry run python -m app.document_conversion offline examples/document_conversion/synthetic-table.json --output out/table
aws cloudformation validate-template --template-body file://infra/document_conversion/registry.yaml
aws cloudformation validate-template --template-body file://infra/document_conversion/stack.yaml
```

Open `out/table/document.html`. Expect rows 1–12 in numeric order, one merged header and an empty cell at row 3 / column 2. Template validation is a read-only AWS check, not an authorization, IAM or deployment success test. Optional local IaC lint: install `cfn-lint` in a separate tools environment and run `cfn-lint infra/document_conversion/registry.yaml infra/document_conversion/stack.yaml`.

## 3. Registry, image build and push

First create a reviewable registry change set:

```powershell
aws cloudformation create-change-set --stack-name "$Prefix-registry" --change-set-name registry-plan --change-set-type CREATE --template-body file://infra/document_conversion/registry.yaml --parameters "ParameterKey=Prefix,ParameterValue=$Prefix"
aws cloudformation wait change-set-create-complete --stack-name "$Prefix-registry" --change-set-name registry-plan
aws cloudformation describe-change-set --stack-name "$Prefix-registry" --change-set-name registry-plan
```

After reviewing and authorizing the registry creation:

```powershell
aws cloudformation execute-change-set --stack-name "$Prefix-registry" --change-set-name registry-plan
aws cloudformation wait stack-create-complete --stack-name "$Prefix-registry"
$RegistryOutputs = (aws cloudformation describe-stacks --stack-name "$Prefix-registry" | ConvertFrom-Json).Stacks[0].Outputs
$RepoUri = ($RegistryOutputs | Where-Object OutputKey -eq 'RepositoryUri').OutputValue
$RepoArn = ($RegistryOutputs | Where-Object OutputKey -eq 'RepositoryArn').OutputValue
$RepoName = ($RegistryOutputs | Where-Object OutputKey -eq 'RepositoryName').OutputValue
$RegistryHost = $RepoUri.Split('/')[0]
$ImageUri = "$($RepoUri):$ImageTag"
aws ecr get-login-password --region $Region | docker login --username AWS --password-stdin $RegistryHost
docker build --platform linux/amd64 -t $ImageUri .
docker run --rm -d --name batchlens-api-local -p 127.0.0.1:8000:8000 $ImageUri
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/ready
Invoke-RestMethod http://127.0.0.1:8000/version
docker stop batchlens-api-local
docker run --rm --entrypoint python $ImageUri -c "import app.document_jobs.worker; print('Worker imports successfully')"
docker push $ImageUri
```

The local image starts with the feature disabled. This proves baseline container startup only; worker import is not worker cloud acceptance. The enabled worker requires the provisioned settings and task role. The same image uses `python -m app.document_jobs.worker` in the worker service. Registry tags are immutable: increment `$ImageTag` for each subsequent build. Review the ECR scan; do not infer security approval simply from scan availability.

## 4. Application infrastructure

Templates create a fresh VPC with two subnets, an internet gateway, free-of-hourly-charge S3/DynamoDB gateway endpoint types, an HTTPS ALB, one API task (0.25 vCPU / 0.5 GiB), one worker task (1 vCPU / 4 GiB), private versioned S3, DynamoDB, work queue and DLQ, Cognito, IAM task roles, logs and two queue alarms. Check current endpoint pricing before treating network costs as zero overall.

**Network choice:** ECS tasks use public IPv4 addresses for outbound HTTPS, no NAT Gateway. API inbound is only from the ALB security group; worker has no inbound rule. ALB ingress is limited to `$AllowedCidr`. Tasks have no SSH endpoint. S3 is private, not a public website. The ALB terminates TLS and forwards HTTP within this VPC security-group boundary; this is not TLS all the way to the container. Outbound HTTPS is not domain-allowlisted. Public IPv4 and ALB costs still apply. For private-subnet production networking, separately design either NAT or all required interface endpoints plus Cognito JWKS access; this template does not silently provision either option.

Create the exact parameter file in UTF-8 (it contains resource identifiers, no secrets):

```powershell
$Parameters = @(@{ParameterKey='Prefix';ParameterValue=$Prefix},@{ParameterKey='ImageUri';ParameterValue=$ImageUri},@{ParameterKey='RepositoryArn';ParameterValue=$RepoArn},@{ParameterKey='DomainName';ParameterValue=$Domain},@{ParameterKey='CertificateArn';ParameterValue=$CertificateArn},@{ParameterKey='AllowedIngressCidr';ParameterValue=$AllowedCidr},@{ParameterKey='ActiveJobs';ParameterValue='2'},@{ParameterKey='JobWorkers';ParameterValue='2'},@{ParameterKey='PageWorkers';ParameterValue='1'})
[System.IO.File]::WriteAllText((Join-Path $PWD 'document-stack-parameters.json'), ($Parameters | ConvertTo-Json), [System.Text.UTF8Encoding]::new($false))
aws cloudformation create-change-set --stack-name "$Prefix-app" --change-set-name app-plan --change-set-type CREATE --template-body file://infra/document_conversion/stack.yaml --parameters file://document-stack-parameters.json --capabilities CAPABILITY_IAM
aws cloudformation wait change-set-create-complete --stack-name "$Prefix-app" --change-set-name app-plan
aws cloudformation describe-change-set --stack-name "$Prefix-app" --change-set-name app-plan
```

Review additions, IAM policies, retention and network exposure. After explicit authorization:

```powershell
aws cloudformation execute-change-set --stack-name "$Prefix-app" --change-set-name app-plan
aws cloudformation wait stack-create-complete --stack-name "$Prefix-app"
$Outputs = (aws cloudformation describe-stacks --stack-name "$Prefix-app" | ConvertFrom-Json).Stacks[0].Outputs
$Outputs | Format-Table OutputKey,OutputValue
$Bucket = ($Outputs | Where-Object OutputKey -eq 'BucketName').OutputValue
$JobsTable = ($Outputs | Where-Object OutputKey -eq 'JobsTable').OutputValue
$QueueUrl = ($Outputs | Where-Object OutputKey -eq 'QueueUrl').OutputValue
$DlqUrl = ($Outputs | Where-Object OutputKey -eq 'DeadLetterQueueUrl').OutputValue
$Pool = ($Outputs | Where-Object OutputKey -eq 'UserPoolId').OutputValue
$ClientId = ($Outputs | Where-Object OutputKey -eq 'UserClientId').OutputValue
$Cluster = ($Outputs | Where-Object OutputKey -eq 'ClusterName').OutputValue
$ApiService = ($Outputs | Where-Object OutputKey -eq 'ApiServiceName').OutputValue
$WorkerService = ($Outputs | Where-Object OutputKey -eq 'WorkerServiceName').OutputValue
$LogGroup = ($Outputs | Where-Object OutputKey -eq 'LogGroup').OutputValue
$AlbDns = ($Outputs | Where-Object OutputKey -eq 'AlbDnsName').OutputValue
```

Now create the DNS CNAME **`$Domain` → `$AlbDns`** at your DNS provider (Route 53 alias also works). The existing certificate must cover `$Domain`, not the autogenerated ALB hostname. Allow DNS propagation and verify:

```powershell
Resolve-DnsName $Domain
Invoke-RestMethod "https://$Domain/health"
aws ecs describe-services --cluster $Cluster --services $ApiService $WorkerService --query 'services[].{Name:serviceName,Desired:desiredCount,Running:runningCount,Events:events[0:3]}'
aws s3api get-bucket-versioning --bucket $Bucket
aws s3api get-public-access-block --bucket $Bucket
```

Success: both services have the expected running count, health returns `ok`, bucket versioning is `Enabled` and all four public-access-block settings are true. `/ready` retains its existing foundation semantics; it does not prove OCR readiness. CloudFormation may take several minutes. If it fails, inspect stack events and ECS task-stop reasons before retrying.

## 5. Approved test-user authentication

The pool allows **admin-created users only**, with no client secret. The UI signs in directly to Cognito and retains the access token only in tab memory. API JWT validation checks RSA signature, issuer, expiry, token use and client ID. Ownership comes from verified `sub`. The API never accepts an owner, source bucket or source key from upload callers. This is a single-user ownership boundary, not enterprise organization tenancy.

Create an approved test user without putting their password in shell history and without sending an email:

```powershell
poetry run python examples/document_conversion/operator.py --region $Region --pool $Pool --email YOUR_APPROVED_TEST_EMAIL
Start-Process "https://$Domain/documents"
```

Choose a unique password with at least 14 characters, uppercase, lowercase, number and symbol. The helper prompts twice and sets a permanent password; rerunning it resets that user's password, so use deliberately. Share access credentials only through an approved channel outside this task. Refresh/logout requires another sign-in; automatic refresh, SSO and MFA flows are outside this small UI. Already-issued JWTs may remain accepted until expiry (60 minutes), even after user disable/logout; no token revocation lookup is claimed.

Only the exact `https://$Domain` origin is allowed by S3 CORS. Browser POST grants are valid for five minutes, bound to an allocated key, exact declared byte size, content type, metadata and AES256 encryption. Start checks metadata, size and PDF signature using a ranged read, and freezes the returned object version. Replaying the grant creates another S3 version but cannot alter the source of an already accepted job. PDF signature checking is not malware scanning or complete PDF validation; unsupported/password-protected PDFs may fail in Textract.

## 6. One-document and concurrent acceptance

Use only an authorized non-confidential PDF for the first test. There is no supplied real PDF or saved real Textract response in this delivery.

1. Sign in; choose or drop the PDF (default limit 25 MiB).
2. The PDF goes directly from the browser to S3. The API persists a job before issuing the grant, verifies the upload, then returns 202 without waiting for OCR.
3. Observe `QUEUED → SUBMITTING → OCR → COLLECTING → RENDERING → SUCCEEDED` or `PARTIAL_SUCCESS`. Fast transitions may happen between UI polls. Phase is exact; no OCR percentage is invented.
4. Download `document.html`, `document.json`, `textract.json` and, if needed, `page-NNNN.html`. URLs expire after 60 seconds and specify the exact result version. Treat these brief bearer URLs as sensitive. The HTML is served as an attachment, never injected into the privileged UI DOM.
5. Compare numeric strings, units, source references, merged headers and representative source pages. Record actual differences. A successful HTTP job is not evidence of perfect OCR.

Select **two independent PDFs** in one batch. Browser uploads are sequential to bound transfer memory; their accepted document OCR jobs overlap up to `ActiveJobs`. Confirm distinct IDs and separate artifacts. Refresh or reopen the UI and sign in: jobs should remain visible. Check that per-page JSON/HTML order is numeric. Sign in as a second approved user and verify the first user's jobs are absent. A direct request to their job ID must return 404.

For restart recovery, after accepting a sample, force a replacement worker task:

```powershell
aws ecs update-service --cluster $Cluster --service $WorkerService --force-new-deployment
aws logs tail $LogGroup --since 10m --follow
```

Verify the same application job reaches a terminal phase and its provider handle remains the same. A replaced worker resumes persisted work after lease expiry/next sweep; at-least-once delivery allows repeated SDK reads and orphaned artifact versions. This does not promise exactly-once execution.

## 7. Concurrency, recovery and failed jobs

| Control | Default | Meaning |
|---|---:|---|
| `ActiveJobs` / `DOCUMENT_ACTIVE_JOBS` | 2 | Shared durable slots in the jobs table bound outstanding document OCR jobs across workers; slots normally remain held through conversion. All replicas must use the same value. Do not lower it while jobs hold higher-numbered slots. |
| `JobWorkers` | 2 | Worker threads per task; bounds simultaneous job steps and their SDK I/O. |
| `PageWorkers` | 1 | Per-job process count for page HTML rendering after global normalization. Setting 2–4 uses real spawned processes; budget for up to JobWorkers × PageWorkers and increase task CPU/memory if required. |
| `DOCUMENT_SDK_IO_CONCURRENCY` | 4 | Shared semaphore bounds concurrent SDK invocations across S3, DynamoDB, SQS and Textract clients per process; also sizes connection pools. Includes SQS long-poll and heartbeats, so a value of 1 serializes them and delays progress. Streaming response reads are additionally bounded by job threads. This is not an account TPS quota. |
| `DOCUMENT_POLL_SECONDS` | 30 | Persisted due-job sweeps and default OCR rescheduling interval; no indefinite per-job sleeping. |
| `DOCUMENT_MAX_FAILURES` | 8 | Bounded failed turns per phase, in addition to at most three SDK attempts per request. Backoff is persisted and capped at 300 seconds. |
| `DOCUMENT_MAX_JOB_SECONDS` | 86,400 | Attempt deadline; a failed recoverable job can receive another bounded window through explicit Resume. |
| Limits | 100,000 blocks, 64 MiB collected JSON, 200 pages | Explicit failure, never silent truncation. PDFs may already incur OCR charges before result limits can be checked. |

One multi-page PDF becomes **one asynchronous Textract job**. AWS owns its internal page scheduling. The application does not split every PDF page into an OCR job.

DynamoDB is the recovery authority. Worker sweeps send due jobs to SQS. API enqueue failure leaves a due job; the next sweep retries it. A worker crash leaves a renewable lease that later expires. Submission intent, exact source version and request token are persisted before the provider call. A crash after submission but before handle commit retries the same token. AWS's idempotency window is finite; automatic application resume is refused after six days. Collection resolves relationships only after all continuation batches have arrived. S3 writes precede the final conditional artifact-reference commit, so a crash may leave unreferenced versions for lifecycle cleanup.

Failed job state also acts as a failure-notification outbox: the sweeper sends a small job-ID/error-code DLQ record and then conditionally marks it sent. A crash in that gap can duplicate the notification. Poison SQS messages use queue redrive after five receives. Failed job records remain authoritative even if DLQ delivery temporarily fails. Terminal-state sweeps release slots left by a crash after a confirmed OCR completion.

**Unknown submission outcome fails closed:** an exhausted SUBMITTING/OCR job can retain its slot while an AWS job might still exist. Correct the underlying access/quota/transient failure and use the UI's **Resume if recoverable**. It preserves the source/token/handle; it is not a new upload. Provider-declared `TEXTRACT_FAILED` is terminal and requires a new explicitly chosen job if you want another OCR attempt. Deterministic conversion errors require investigation of saved raw JSON. No automatic source deletion or cancellation API is provided.

Inspect operational state (outputs can contain document filenames/metadata, so keep them private):

```powershell
aws logs tail $LogGroup --since 30m
aws sqs get-queue-attributes --queue-url $QueueUrl --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible
aws sqs get-queue-attributes --queue-url $DlqUrl --attribute-names ApproximateNumberOfMessages
aws sqs receive-message --queue-url $DlqUrl --max-number-of-messages 5 --visibility-timeout 30
$JobId = "YOUR_APPLICATION_JOB_ID"
$JobKey = @{pk=@{S="job#$JobId"}} | ConvertTo-Json -Compress
[System.IO.File]::WriteAllText((Join-Path $PWD 'job-key.json'), $JobKey, [System.Text.UTF8Encoding]::new($false))
aws dynamodb get-item --table-name $JobsTable --key file://job-key.json --consistent-read
```

Do not delete slot records just to make a stuck queue move: first recover the persisted handle and confirm the provider is terminal. If a handle has expired, leave the failed job for review; manual slot retirement is an operator decision after confirming the old execution cannot be active. Do not redrive all DLQ messages indiscriminately: valid failure notifications do not have the work-message schema. Use the job Resume action for recoverable work and inspect poison messages separately. Logs intentionally omit document text, provider messages, tokens and presigned URLs; only job IDs, phases and safe error codes/types are logged.

The development store scans small job metadata tables for due/recent jobs. Metadata retention bounds growth, but scanning is not the scalable design for a large customer workload. Add indexed due/owner access and capacity controls before that use. Queue-age/DLQ CloudWatch alarms are provisioned without notification recipients; inspect them in the console or separately authorize a subscription.

## 8. Costs, stopping and teardown

No numerical price estimate is quoted. Check current regional [Textract pricing](https://aws.amazon.com/textract/pricing/), [Fargate pricing](https://aws.amazon.com/fargate/pricing/), [ALB pricing](https://aws.amazon.com/elasticloadbalancing/pricing/) and [VPC/public IPv4 pricing](https://aws.amazon.com/vpc/pricing/) before deployment. Include analyzed pages and enabled TABLES/LAYOUT features, worker/API running hours, ALB hours/LCUs, task and ALB IPv4 addresses, S3 object versions/requests, DynamoDB requests/PITR, SQS, ECR and logs. Set a personal development spending budget/notification in AWS Billing before running multiple PDFs. Larger thread/process limits raise memory and compute needs; they do not lower per-page OCR pricing.

Stop new uploads first. Let accepted jobs settle or record their handles; stopping workers does not cancel already-running Textract jobs. To pause task compute:

```powershell
aws ecs update-service --cluster $Cluster --service $ApiService --desired-count 0
aws ecs update-service --cluster $Cluster --service $WorkerService --desired-count 0
```

Later resume with `--desired-count 1`. These direct changes are stack drift; set `ApiCount`/`WorkerCount` consistently in a subsequent reviewed CloudFormation update. Even at zero tasks the ALB, its public addresses, retained storage, ECR and other resources may incur charges. For updates, create a new named change set with `--change-set-type UPDATE`, reuse all parameter values deliberately, review, and execute. Registry image tags cannot be overwritten.

**Retention choice:** default lifecycle removes current and noncurrent objects under `documents/` after 30 days; DynamoDB TTL removes job metadata on its own asynchronous schedule. Raw JSON and all page/results share the same policy. Logs default to 14 days; the DLQ retains messages up to 14 days. S3/DynamoDB/Cognito/logs/DLQ/ECR resources are retained on stack deletion, but existing lifecycle/TTL/log-retention policies continue operating. `Retain` is not a permanent backup. Export required evidence or explicitly review a retention-policy change before deletion.

Save resource names before teardown:

```powershell
$Outputs | ConvertTo-Json -Depth 10 | Set-Content -Encoding utf8 retained-resources.json
aws cloudformation delete-stack --stack-name "$Prefix-app"
aws cloudformation wait stack-delete-complete --stack-name "$Prefix-app"
aws cloudformation delete-stack --stack-name "$Prefix-registry"
aws cloudformation wait stack-delete-complete --stack-name "$Prefix-registry"
```

This removes compute/networking and the work queue while retaining the identified data-bearing resources. A retained bucket has all public-access-block settings and default encryption; do not add a public policy to recover it. To **delete retained PDFs/results**, separately review and authorize deletion of all object versions and delete markers in that dedicated bucket through the S3 console (an ordinary `aws s3 rm --recursive` does not purge versions), then delete the empty bucket. Caller-owned existing S3 inputs used by the standalone CLI are outside this stack and must not be automatically deleted.

After explicitly choosing to delete the retained metadata, users, logs, failure records and registry images, these are the corresponding destructive commands:

```powershell
aws s3api delete-bucket --bucket $Bucket
aws dynamodb delete-table --table-name $JobsTable
aws cognito-idp delete-user-pool --user-pool-id $Pool
aws logs delete-log-group --log-group-name $LogGroup
aws sqs delete-queue --queue-url $DlqUrl
aws ecr delete-repository --repository-name $RepoName --force
```

Also remove your DNS CNAME. The pre-existing ACM certificate/domain remain yours; do not delete shared assets. Review Billing and the CloudFormation retained-resource list afterward instead of assuming zero remaining cost.
