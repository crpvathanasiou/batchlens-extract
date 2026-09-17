# 06 — Security and Data Handling

**Status:** Product security requirements. Implementation evidence is separated from future design. No compliance certification checklist.

Owner of product data protection, trust boundaries, data handling, and evidence for security claims. Artifact/lifecycle semantics: [05_pipeline_contracts.md](05_pipeline_contracts.md). General secure coding: [02_code_quality_standards.md](02_code_quality_standards.md). Product boundaries: [00_project_reference.md](00_project_reference.md).

---

## 1. Protected data classes

Data protection extends to **derived** artifacts, not only original PDFs.

| Class | Examples |
|-------|----------|
| Source documents | Original manufacturing PDFs |
| Derived page content | Page images, OCR/extracted text |
| Structured results | Extracted JSON, recipe representations |
| Review artifacts | Human corrections and review revisions |
| Projections | Graph projections, tabular exports |
| Reports | Human-readable summaries of results/findings |
| Optional enrichment | Embeddings, catalog snapshots, retrieved snippets |
| Temporary artifacts | Working files, intermediate conversions |
| Diagnostic records | Logs, traces, error reports (minimized; stdout operational logs only today) |
| Future audit ledger | Append-only event references (APPROVED TARGET / not implemented; see [05](05_pipeline_contracts.md) §6) |

Historical traceability ([02](02_code_quality_standards.md)) must coexist with retention/deletion policy here. Do **not** imply unlimited retention of confidential content.

---

## 2. Trust boundaries (required conceptually)

Describe required access boundaries **without** selecting services or claiming they are implemented.

```text
Users / customers
→ Application (API / review UI)
→ Storage and workers (when the document feature is enabled)
→ External providers (OCR, LLM, hosting, etc.)
```

Requirements:

- Authorized access to each artifact class
- Protected transmission and storage when those paths exist
- Least privilege for components and roles
- Safe secret handling (no secrets in source, images, or logs)
- Sensitive-data minimization in logs and diagnostics
- Controlled export and deletion

Exact retention durations, regions, tenancy model, identity provider, encryption/key configuration, and egress controls: **OPEN**.

---

## 3. External providers

Before confidential customer use, decide explicitly:

- What data is sent to each provider
- Provider retention and training usage
- Destinations / subprocessors / regions as applicable

**AWS hosting alone does not prove AWS-only processing.** Optional catalog/RAG data must remain within appropriate customer access boundaries and stay distinguishable from document evidence ([00](00_project_reference.md)).

Source documents and extracted text are **untrusted data**. Extracted text must not become instructions that override application policy or authorization ([02](02_code_quality_standards.md)).

---

## 4. UI claims

The UI should communicate only **implemented** protections with verifiable evidence. Do not claim certification, guaranteed confidentiality, penetration-test results, or AWS-only residency before established.

---

## 5. Evidence register (observed baseline only)

| Requirement | Current evidence | Verification needed | Permitted UI claim today |
|-------------|------------------|---------------------|--------------------------|
| App starts without embedding secrets in code | Settings load `OPENAI_API_KEY` from env; `.env` gitignored (pattern) | Confirm no secrets committed | "API keys are configured via environment, not hard-coded" — only if still true at claim time |
| Non-root container user | Dockerfile uses non-root `appuser` (baseline design) | Confirm image still runs as non-root | "Container runs as non-root" — only after verified for the shipped image |
| Foundation health endpoints | `/health`, `/ready`, `/version` implemented and historically smoke-tested | Re-verify after runtime changes | Liveness/readiness as implemented — not "document processing ready" |
| Dependency security update (Starlette) | B2.1 report: Starlette 0.48.0 | Keep lock reviewed on changes | Do not claim "fully hardened" product security |
| Authentication / authorization | Cognito JWT verification and ownership-hiding job lookup exist in code (`document_jobs.auth`, documents/review APIs). Local harness uses synthetic `local-test-reviewer`. | Live Cognito authorization, token revocation, and production IAM | **No production/auth claim**. Do not describe the local harness as Cognito proof |
| Encrypted storage / KMS | IaC/settings may name encryption; **not verified** | Design + verify | **No claim** |
| Provider data-processing agreements | **Not verified** | Obtain and record | **No claim** |
| Isolation / penetration tests | **Not verified** | Perform if required | **No claim** |
| Document retention/deletion controls | Job/review expiry fields exist in contracts; deletion workflows **absent** | Design in remaining M-Design+ | **No claim** |
| Persistent audit ledger | **Absent** (direction only in [05](05_pipeline_contracts.md) §6) | Intended-use / provenance design before implementation | **No claim**. Stdout logs are not the audit ledger |

Populate only from observed baseline facts. Do not invent provider policies or production security.

---

## 6. Open decisions

- Retention durations and deletion workflows
- Data regions and residency statements
- Tenancy / customer isolation model
- Identity provider and authorization model (Cognito is the implemented intended provider in code; live verification **OPEN**)
- Encryption and key management configuration
- Egress controls and allowed external destinations
- Provider processing, retention, and training terms before confidential use
- Audit-ledger location, retention, and access (direction in [05](05_pipeline_contracts.md); implementation deferred)

Link lifecycle artifact definitions to [05](05_pipeline_contracts.md). Do not mandate paid security tooling in this document.
