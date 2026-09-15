# Verification evidence — 2026-09-15

The supplied BatchLens template now contains the document-conversion reference slice and its AWS deployment assets. This report distinguishes source/local checks from cloud and document acceptance. No AWS deployment, upload of a real PDF, paid processing, commit or push was performed.

## Implemented and locally tested

| Check | Observed result |
|---|---|
| Python runtime | Python 3.11.16, matching the project's 3.11 requirement |
| Dependency integration | Poetry 2.4.3 `add` / lock regeneration / install succeeded; no hand-edited lock |
| Existing locked dependency versions | All preserved; only feature-required runtime/dev packages and their dependencies added |
| Ruff lint | PASS, entire project |
| Ruff format check | PASS, 42 Python files |
| Pyright strict | PASS, zero errors/warnings for configured `src` + `tests`; operator example separately checked with zero errors |
| pytest | **80 tests passed**: 36 existing + 44 document-feature tests; no skipped tests |
| Offline examples | Both saved synthetic JSON examples converted to document JSON, full HTML and per-page HTML |
| Page process pool | Sequential and two-process projections match; spawned processes used, bounded submissions |
| Local API smoke | TestClient returns 200 for existing system endpoints and HTML/JS/CSS assets; enabled feature lifespan, config, authentication boundary and isolation headers tested with injected local services |
| UI JavaScript | `node --check` passed; no interactive browser end-to-end test claimed |
| Python package build | Poetry wheel and sdist built; wheel inspected for worker and all three UI assets |
| CloudFormation | `cfn-lint` 1.56.3 passed both registry/application templates, no errors/warnings |
| Original LLM wrapper | Source and existing tests byte-for-byte unchanged and still unwired |
| Integration patch | Generated relative to the uploaded source snapshot and checked against a clean extracted copy |
| Delivery hygiene | Archive excludes `.env`, credentials, caches, virtual environments, build outputs, real PDFs and unrelated legacy utilities |

The ordinary initial full test run encountered **one environment-specific failure in an existing wrapper test**: this runtime injects a `socks5h` proxy URL unsupported by the original locked HTTPX 0.27.2 client constructor. No wrapper/dependency source was changed to mask it. The full suite subsequently passed in a verification-only process with all IP socket connections blocked and injected proxy variables removed from that process. SDK tests use dummy credentials with Stubber/fakes, and Cognito tests sign local RSA tokens. This is offline evidence, not network/cloud acceptance. The included `scripts/document-offline-quality.py` reproduces that narrowly isolated test run if the same sandbox-proxy issue occurs; normally use the existing quality commands directly.

Focused regression evidence covers numeric 12-row tables; merged row/column spans and header member references; empty-cell alignment; table/word/cell reordering; shared title suppression; nested lists and selections; hostile-looking text escaping and anchors; partial line/table overlap; numeric PDF-page order; repeatability; unresolved/missing references; figure location/limitations; input/size rejection; cross-pagination references; all four AWS job outcomes; bounded wait with handle retention; service-code throttling; streaming local staging; immutable source checks; shared SDK concurrency bounds; prompt HTTP acceptance; serialized state reload; two concurrent isolated jobs; duplicate delivery/start; expired leases; lost submit responses with token reuse; enqueue recovery; upload replay; global slots; terminal-slot recovery; failure notification outbox; deadlines/retry exhaustion; Cognito signature/issuer/client/expiry/token-use checks; DynamoDB CAS and paginated owner scan; owner-denied downloads; and version-bound attachment grants.

## Not run / not established

| Gate | State and reason |
|---|---|
| Docker build and running API/worker image | **NOT RUN** — this execution environment has no Docker, Podman or Buildah executable/server. A Python wheel build is not a container build. Exact build/local smoke commands are in the AWS guide. |
| AWS `validate-template`, change set, IAM evaluation or deployment | **NOT RUN** against a configured account; local cfn-lint does not prove these |
| Live AWS upload → job → Textract → artifacts | **NOT RUN** — no configured deployment and no explicitly authorized live sample |
| Live concurrent jobs / worker replacement / Cognito browser sign-in | **NOT RUN**; local state/auth tests do not prove real service integration |
| Real saved Textract/PDF fidelity | **NOT RUN** — neither a representative PDF nor saved real Textract response was supplied |
| Multimodal-provider comparison | **NOT RUN** — comparison samples/provider authorization/reference outputs were absent |
| Pixel-perfect layout, perfect OCR or recipe extraction accuracy | **Not claimed** |

## Remaining integration/operating limits

- Review the integrated snapshot/patch before merging into a newer checkout; preserve local edits and merge manifests via Poetry.
- Complete the missing Docker and AWS gates using the ordered operator guide before calling this cloud-accepted.
- A controlled DNS name and existing regional ACM certificate are prerequisites for the public HTTPS deployment. Only approved test users are intended.
- The converter collects/indexes complete bounded responses in memory. Default limit: 100,000 blocks, 64 MiB provider JSON and 200 pages. Oversized/unresolvable content fails or warns explicitly; these are not OCR-quality guarantees.
- Explicit table relationships remain essential. When layout/table associations or page assignments cannot be recovered safely, warnings and raw data support manual review. Fallback top/left reading order is not a reliable multi-column solution. Cross-page table joining and model-specific chunking are deferred.
- Development DynamoDB scans, approved-user access, bounded job execution and per-attempt deadlines do not constitute enterprise tenancy, request admission control, a monthly spend cap or production capacity validation.
- Unknown submission outcomes may retain a durable capacity slot until recovered/reviewed. No exactly-once execution or permanent Textract idempotency is promised.
- The dev network uses outbound public IPv4, private S3/DynamoDB data, no NAT, HTTPS ALB ingress and HTTP from ALB to API within its security-group boundary. No outbound domain allowlist or TLS-to-container claim.
- No malware scanning, immediate JWT revocation lookup, MFA/SSO UI, enterprise role policy or compliance validation is included. Download grants are short-lived bearer capabilities.
- Retained resources can continue costing money and configured lifecycle/TTL deletion continues after stack teardown. The operator guide separates pause, retain and destructive cleanup.
