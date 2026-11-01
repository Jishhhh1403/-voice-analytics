# Build Prompt: Banking Customer Intelligence & Product Backlog Validation Platform on Google Cloud

## 0. Your role and delivery standard

Act as a senior staff software engineer, cloud architect, applied NLP/ML engineer, data engineer, and pragmatic product-minded technical lead. Design and implement a working proof-of-value (PoV), not merely a concept document or static UI. Make sound engineering decisions, explain material trade-offs, and produce a runnable repository with Docker support and Google Cloud deployment assets.

Build a **Banking Customer Intelligence & Backlog Validation Platform**. The application converts unstructured banking-app customer feedback into evidence-backed customer problems mapped to banking journeys. Product owners then upload backlog items as CSV; the system evaluates whether each backlog addresses the customer problems most strongly evidenced in the feedback and produces an explainable validation/decision report.

Do not turn this into a generic sentiment dashboard. The central product value is traceability:

`raw customer feedback -> extracted intent/aspect/problem -> canonical customer problem -> banking journey -> customer evidence -> backlog alignment -> PO decision report`

## 1. Fixed product decisions and PoV boundaries

These decisions are fixed for this implementation:

1. **Journey mapping: hybrid.** Start with a predefined, versioned banking application taxonomy. Allow the system to discover candidate problem categories not covered by the current taxonomy. New taxonomy categories require human approval before becoming canonical.
2. **Intelligence input: text only.** The initial intelligence pipeline consumes customer feedback text and permitted metadata from the CSV. Do not require clickstream, transaction logs, core banking data, or backend telemetry.
3. **Backlog capability: validation only.** Product owners upload existing backlog items as CSV. The system validates alignment and coverage against customer problems. Do not generate a new backlog or automatically change product priorities.
4. **Feedback source of truth: Google Cloud Storage (GCS).** The original feedback CSV is stored as an immutable/versioned object in a GCS bucket. All ingestion starts by reading a `gs://` object URI and its object generation. BigQuery holds derived, queryable tables; it is not the authoritative copy of the original CSV.
5. **Analytics store: BigQuery.** Persist Module A–E outputs and pipeline metadata in BigQuery tables. The UI reads analytics and validation results from BigQuery through the backend API, never directly from the browser.
6. **Runtime: Google Cloud.** All deployed application and processing code must run on Google Cloud. Use Docker images and managed services. The solution must be manageable from Google Cloud Console and deployable repeatably with `gcloud` and preferably Terraform.
7. **PoV scale:** support at least 2,000 feedback rows and at least 100 backlog rows per upload without architectural changes. Keep the design able to scale later, but do not over-engineer the PoV.

## 2. Required Google Cloud architecture

Use the following default architecture unless a documented technical constraint requires a change:

- **Cloud Storage:** immutable raw feedback CSV objects; optionally store uploaded backlog CSVs and generated report exports here. Enable object versioning or otherwise preserve object generations. Use separate prefixes such as `feedback/source/`, `backlogs/uploads/`, `reports/`, and `dead-letter/`.
- **Cloud Run services:** host the web application and FastAPI backend. The backend is the only service allowed to query BigQuery or start processing jobs for the user.
- **Cloud Run Jobs:** execute containerised batch stages that read GCS objects, validate/normalise records, run CPU-oriented Python processing, and write results to BigQuery. Cloud Run Jobs are the default for bounded batch containers that start, run to completion, and exit.
- **Vertex AI:** use Vertex AI for managed model inference where appropriate. Provide a model adapter interface so extraction can use an approved Vertex AI Gemini model or a self-hosted/open-source model in a Vertex AI Custom Job. Use a Vertex AI Custom Job only when custom model execution, GPU/CPU isolation, or a larger batch workload justifies it. Do not create a model-training job for every feedback upload. The PoV should use pretrained models; training/fine-tuning is out of scope unless explicitly enabled.
- **Workflows:** orchestrate the stages, pass `run_id`, GCS URI/generation and configuration between them, wait for job completion, retry transient failures, and record the final status. A Cloud Storage Eventarc trigger may be an optional automatic ingestion trigger, but the UI must also support an explicit “Run feedback pipeline” action against an existing GCS object.
- **BigQuery:** store staging, curated, intelligence, taxonomy, backlog and validation tables. Use partitioning/clustering where appropriate. Keep all table names and schemas in migrations or versioned SQL files.
- **Artifact Registry:** store versioned Docker images.
- **Cloud Build:** build/test/push images and deploy Cloud Run services/jobs. Include a reproducible deployment workflow.
- **Secret Manager:** store provider/API credentials and secrets. Never commit secrets or place secrets in Docker images.
- **Cloud Logging and Cloud Monitoring:** structured logs, job execution visibility, latency/error metrics and alerts.
- **IAM:** use dedicated service accounts and least-privilege permissions for each runtime. Do not use service-account key files in production; use attached service identities / Application Default Credentials.

### 2.1 Orchestration recommendation

Use **Google Cloud Workflows** as the control plane. Define a feedback workflow with explicit, observable stages:

`validate_source -> module_A_ingest -> module_B_extract -> module_C_discover -> module_D_map -> module_E_publish -> mark_run_complete`

A stage may run as a Cloud Run Job or call a Cloud Run service/Vertex AI API. For the PoV, it is acceptable for one container image to expose separate CLI commands for stages, while Workflows invokes the stage jobs sequentially. Keep stage boundaries and contracts independent so stages can later be deployed separately.

Do not use Vertex AI Training/Pipeline infrastructure merely because the product contains NLP. Use the simplest managed execution service appropriate to each workload. The platform should make it clear which work runs in Cloud Run and which inference calls run through Vertex AI.

### 2.2 High-level architecture diagram

Produce and include an architecture diagram in the repository documentation. It should show:

`Browser -> Cloud Run frontend -> Cloud Run FastAPI backend -> Workflows -> Cloud Run Jobs / Vertex AI -> BigQuery`

and the data paths:

`GCS raw feedback CSV -> Module A -> BigQuery staging/curated`

`BigQuery curated feedback -> Modules B/C/D/E -> BigQuery intelligence tables`

`Backlog CSV upload -> GCS backlog object -> Module F normalisation -> Module G validation -> BigQuery validation tables -> UI report`

## 3. Repository structure and engineering conventions

Create a clean monorepo similar to:

```text
banking-customer-intelligence/
  frontend/                    # React + TypeScript UI
  backend/                     # FastAPI REST API, auth and query layer
  pipelines/
    common/                    # config, logging, BigQuery/GCS clients, contracts
    feedback/                  # Modules A-E
    backlog/                   # Modules F-G
    jobs/                      # Cloud Run Job entrypoints / CLI
  taxonomy/
    banking_taxonomy_v1.yaml
  sql/
    migrations/
    views/
    assertions/
  workflows/
    feedback_pipeline.yaml
    backlog_validation.yaml
  infra/
    terraform/                 # optional but preferred repeatable provisioning
  tests/
    unit/
    integration/
    fixtures/
  docker/
  scripts/
  docs/
  .env.example
  docker-compose.yml
  Makefile
  README.md
```

Use Python 3.11+ with type hints, Pydantic v2, FastAPI, pytest and structured JSON logging. Use React + TypeScript (Vite is fine) for the UI. Pin dependencies. Add linting and formatting (Ruff for Python, ESLint/Prettier for frontend). Keep configuration in environment variables and typed settings classes. No hardcoded GCP project IDs, bucket names, dataset names, regions, model names or credentials.

Provide Dockerfiles for the frontend, backend and batch worker. Use multi-stage builds, non-root runtime users, health checks where suitable, minimal base images and `.dockerignore`. Supply a local Docker Compose environment with local/mock adapters so the application can be run without a GCP account. Cloud deployments must use real GCP adapters and Application Default Credentials.

## 4. Data contracts and source CSV

The raw feedback source CSV uses these columns:

- `feedback_id` — stable source record identifier.
- `submitted_at` — ISO-8601 timestamp, UTC where available.
- `source_type` — e.g. `app_store_review`, `in_app_feedback`, `post_interaction_survey`, `complaint_portal`, `support_chat_summary`.
- `source_channel` — e.g. `google_play`, `apple_app_store`, `in_app`, `survey`, `complaint_portal`, `support_chat`.
- `platform` — Android, iOS, Web or Unknown.
- `app_version` — optional application version.
- `language` — language code.
- `synthetic_customer_ref` — optional pseudonymous synthetic reference; never treat as a real identity.
- `rating_1_to_5` — optional integer rating.
- `feedback_title` — optional short title.
- `feedback_text` — raw, unstructured customer comment. This is the primary NLP input.
- `is_synthetic` — boolean-like source marker; the supplied PoV fixture is synthetic.

Treat the CSV as untrusted input. Validate headers, encoding, delimiter, row limits, nulls, malformed timestamps and ratings. Reject or quarantine invalid rows with row-level error reasons; do not silently discard them. Support UTF-8 and UTF-8 with BOM. Do not place raw feedback text in ordinary application logs.

Create versioned Pydantic contracts for each module's input and output. Persist contract/schema version and pipeline run ID with every derived record.

## 5. Feedback intelligence pipeline: Modules A-E

### Module A — Ingestion, validation and preprocessing

Input: `gs://<feedback-bucket>/<object-key>` plus object generation and `run_id`.

Responsibilities:

1. Read the object directly from GCS using the runtime service account.
2. Verify allowed file type, size, CSV headers, encoding and row count.
3. Calculate a SHA-256 checksum and capture bucket, object name, generation, size, checksum, upload time and original filename in an ingestion manifest.
4. Validate mandatory fields and types. Generate a stable internal feedback key. If `feedback_id` is absent in a future source, derive an idempotent key from source identity and content hash; do not rely on row number alone.
5. Normalise timestamps to UTC, trim whitespace and normalise Unicode. Preserve original source text in the restricted raw zone and create a redacted text version for model processing.
6. Detect and redact sensitive data (account numbers, phone numbers, email addresses, names, card-like numbers and other PII) before sending text to a model. Store only redacted data in downstream intelligence tables. Do not log PII.
7. Deduplicate exact repeated feedback using a content fingerprint while retaining source-record provenance. Do not collapse merely similar complaints in Module A; semantic grouping belongs in Module C.
8. Support multi-line CSV cells and quoted commas correctly.
9. Write ingestion status, accepted/rejected counts and row-level errors to BigQuery.
10. Make the stage idempotent using `run_id`, source object generation and content fingerprint. A retry must not duplicate records.

Outputs: ingestion manifest, validated feedback records and quarantine/error records in BigQuery.

### Module B — Intent, aspect, sentiment and problem extraction

Process each feedback record at sentence/claim level. One feedback record may contain multiple intents, aspects and problems; do not force one label per comment.

Extract at least:

- `customer_intent`: what the customer is trying to accomplish (e.g. transfer_funds, add_beneficiary, download_statement, view_balance, block_card, complete_kyc).
- `aspect`: product area or interaction being discussed (e.g. OTP, transaction status, statement download, biometric login).
- `reported_problem`: concise, neutral description of the obstacle described by the customer.
- `reported_symptom`: what the customer says happened (e.g. pending, timeout, duplicate debit, blank PDF, missing notification).
- `sentiment`: positive, negative, neutral or mixed, linked to the relevant aspect rather than only the whole comment.
- `emotion`: optional controlled label (e.g. frustration, confusion, anxiety, satisfaction) with unknown/none allowed.
- `customer_effort`: explicit or inferred-from-text effort descriptor (low/medium/high/unknown). Do not claim behavioural measurement.
- `reported_outcome`: completed, failed, blocked, abandoned, workaround_used or unknown. Only assign an outcome supported by text.
- `evidence_span`: exact substring(s) from the redacted source text supporting each extracted item.
- `language`, `model_id`, `prompt_version`, `schema_version`, `extraction_timestamp`.

Important semantic distinctions:

- Intent = customer's goal.
- Aspect = feature/journey element being discussed.
- Problem = reported obstacle.
- Symptom = observed manifestation described by the customer.
- Root cause = technical explanation. Do not infer or claim root cause from feedback text alone.

Use a provider-independent `ExtractionProvider` interface. The initial production adapter may call an approved Vertex AI Gemini model with structured JSON output. A second adapter may use a fine-tuned Hugging Face classifier or another approved model. Make model name/version configurable. Use bounded concurrency, rate limiting, exponential backoff for transient errors, request timeouts and a dead-letter path for persistent failures. Validate model output using Pydantic; reject invalid JSON, enum violations and evidence spans that cannot be found in the source text. Persist failed records for review rather than dropping them.

Do not use an LLM's self-reported confidence as calibrated probability. Store model confidence as an uncalibrated signal if returned, and maintain a separate validated confidence/review status based on evaluation data and human review.

### Module C — Semantic problem discovery and consolidation

Goal: group differently worded feedback that refers to the same customer problem while keeping distinct failure modes separate.

Implement:

1. Generate embeddings from the extracted `reported_problem` / evidence-bearing problem statement, not only the entire feedback comment.
2. Use a configurable embedding provider. Prefer an approved Vertex AI embedding model or a Sentence Transformers model executed in a controlled Google Cloud container. Persist model name/version and vector dimensions.
3. Retrieve candidate duplicates using vector similarity and keyword/BM25 search. Apply filters for language and relevant journey where useful.
4. Cluster candidate problem statements using an evaluated algorithm such as HDBSCAN/BERTopic. Keep algorithm, parameters and model version configurable. Include an unassigned/noise category; do not force every record into a cluster.
5. Use an LLM only to propose cluster labels and concise cluster descriptions grounded in member evidence. The LLM must not invent causes or facts.
6. Persist canonical `customer_problem` records and explicit `problem_evidence` links. Preserve many-to-many relationships between feedback/extracted insights and canonical problems.
7. Track cluster lifecycle: candidate, in_review, accepted, merged, split, rejected, deprecated. Human decisions are auditable.
8. Support reprocessing with new model versions without destroying prior results. Store run/model/taxonomy versions.

Avoid equating embedding similarity with proof that two issues are identical. Similarity is a retrieval signal; semantic grouping requires scope/failure-mode checks and human evaluation for ambiguous clusters.

### Module D — Hybrid banking journey mapping

Create a versioned banking taxonomy in YAML/JSON, initially covering at least:

- Authentication: login, password reset, OTP, biometric verification, session management.
- Payments: UPI, IMPS, NEFT, RTGS, bill payments, recharge, transaction confirmation, refunds.
- Beneficiary management: add, verify, edit, delete, select beneficiary.
- Accounts: account overview, balance enquiry, transaction history, account details.
- Statements: date-range selection, generation, download, sharing.
- Cards: card controls, limits, block/unblock, replacement, online/international usage.
- Deposits: fixed deposit booking, maturity, renewal, premature closure, deposit advice.
- Loans: eligibility, application, document upload, status, EMI and repayment schedule.
- Onboarding/KYC: identity documents, selfie, video KYC, address verification.
- Support/disputes: complaint creation, tracking, chat/call support, transaction dispute.
- Notifications: push/SMS/email alerts and preference management.
- Navigation/performance: search, home screen, application stability and loading.

Each taxonomy node must have `node_id`, `parent_id`, `node_type`, `display_name`, `description`, `synonyms`, `version`, `status` and optional aliases. Distinguish the app's module/feature taxonomy from the customer journey stage. A problem may relate to more than one node, but require a primary mapping where possible.

Mapping process:

1. First attempt deterministic/lexical and embedding-assisted mapping to known nodes.
2. Evaluate candidate nodes using the problem statement, intent, aspect and supporting evidence.
3. Return primary node, optional secondary nodes, confidence signal, rationale and evidence.
4. If no suitable node exists, mark it `UNMAPPED` and create a taxonomy proposal with suggested name, parent candidate, description, example evidence and reason.
5. Require a human reviewer to approve a new node or change a canonical mapping.
6. Version taxonomy changes. Do not silently remap historical records; retain the taxonomy version used for each mapping.

### Module E — BigQuery publication and customer problem analytics

Publish clean, queryable, versioned outputs. BigQuery must be the serving store for analytics, not a substitute for raw GCS source data.

Create at least these BigQuery datasets/tables (names may be adjusted but responsibilities must remain clear):

- `ops.pipeline_runs` — pipeline stage status, timestamps, input object generation, counts, error details and code version.
- `ops.ingestion_manifests` — GCS source URI, generation, checksum, file metadata and accepted/rejected rows.
- `staging.feedback_raw_metadata` — source-level metadata and restricted references; do not expose raw PII broadly.
- `curated.feedback_records` — validated, deduplicated, redacted feedback records.
- `intelligence.extracted_insights` — one row per extracted insight/problem mention, with intent, aspect, sentiment, outcome, evidence span and model provenance.
- `intelligence.customer_problems` — canonical problem records and lifecycle state.
- `intelligence.problem_evidence` — links canonical problems to feedback IDs and evidence spans.
- `intelligence.problem_clusters` — cluster metadata, labels, algorithm and version.
- `journey.taxonomy_nodes` — versioned banking taxonomy.
- `journey.problem_mappings` — primary/secondary journey mapping, rationale, status and taxonomy version.
- `analytics.problem_metrics_daily` — daily/weekly aggregates for feedback volume, sentiment mix, source mix, trend and distinct synthetic customer references where present.
- `governance.review_decisions` — human review and taxonomy decisions.

Store embeddings in a dedicated table or a supported BigQuery vector column representation. For the 1.5k–2k PoV data size, do not introduce a separate vector database unless benchmarked need justifies it. Use BigQuery vector search or application-side similarity for the PoV; document the trade-off. Add partitioning by date and clustering by useful identifiers/categories where it improves queries. Create SQL views for dashboard-friendly aggregates.

Use parameterised queries and explicit selected columns; never use `SELECT *` in production API code. Apply least privilege and row/column-level controls where appropriate.

## 6. Backlog validation pipeline: Modules F-G

### Module F — Backlog CSV upload, validation and normalisation

The PO uploads a CSV through the web platform. The backend stores the uploaded file in GCS under `backlogs/uploads/<tenant>/<upload_id>/...`, records metadata and starts a Workflows execution. Retain the upload as an immutable object for auditability.

Required backlog CSV columns:

- `backlog_id` — unique item key within the source system.
- `title` — short backlog title.
- `description` — problem/solution description.
- `acceptance_criteria` — plain text; allow newline or delimiter-separated criteria and document the format.
- `product_area` — optional known banking module.
- `priority` — optional source priority; preserve as source metadata, do not treat it as ground truth.
- `business_goal` — optional business objective.
- `source_system` — optional source such as Jira or manual.

Validate duplicate IDs, missing title/description, malformed rows, CSV injection risk and excessive file sizes. Return row-level errors with downloadable error details. Normalise title, description and acceptance criteria into a structured backlog record. Do not overwrite the original uploaded CSV.

### Module G — Backlog-to-customer-problem validation

For each backlog item:

1. Extract a structured backlog intent/outcome, product area, intended scope and testable acceptance-criteria requirements. Preserve the original text.
2. Retrieve candidate canonical customer problems using hybrid semantic and lexical search, with relevant journey/taxonomy filters.
3. Evaluate each candidate relationship using structured criteria:
   - `ADDRESSES` — the backlog directly addresses the described customer problem.
   - `PARTIALLY_ADDRESSES` — some but not all of the problem scope is covered.
   - `RELATED_BUT_NOT_SOLVING` — same feature/journey, but the backlog does not resolve the reported obstacle.
   - `NO_CLEAR_RELATIONSHIP` — insufficient evidence of alignment.
   - `CONTRADICTS_OR_OUT_OF_SCOPE` — the proposed scope conflicts with the problem or is unrelated.
4. Evaluate intent alignment, problem alignment, journey alignment, acceptance-criteria coverage, evidence quality and contradictory evidence.
5. Cite supporting feedback IDs and exact redacted evidence spans for every substantive validation claim.
6. Identify unaddressed high-evidence problems and backlog acceptance-criteria gaps.
7. Produce a human-readable report and machine-readable JSON report.
8. Do not automatically reorder, approve, reject or edit the PO's backlog. The system provides an evidence-backed recommendation and the PO makes the decision.

Avoid using raw embedding similarity as a final validation score. Similarity is only candidate retrieval. The final relationship must be justified by problem scope and acceptance criteria. Use calibrated evaluation thresholds. Where evidence is weak or conflicting, return `NEEDS_REVIEW`.

Suggested output fields:

- backlog ID, title and source upload ID.
- overall customer-evidence alignment: strong / partial / weak / unsupported / needs_review.
- matching customer problems, relationship type and rationale.
- supporting feedback count and evidence references.
- journey coverage.
- acceptance criteria coverage and missing scenarios.
- high-priority customer problems not covered by this backlog.
- contradictory evidence or uncertainty.
- evaluation/model/prompt/schema versions.
- report generated timestamp and reviewer status.

### 6.1 Decision report semantics

Separate these concepts:

- **Customer evidence alignment:** how well this backlog addresses problems evidenced in the feedback dataset.
- **Organisational priority:** whether the work should be prioritised considering strategy, regulatory obligations, risk, delivery cost, dependencies and business value.

The PoV may display provided `business_goal` and `priority` metadata, but it must not claim to calculate an organisation's true priority from customer text alone. Label unsupported business context as `NOT_PROVIDED`. Regulatory/security-critical work must not be downgraded because complaint frequency is low.

## 7. Web platform requirements

Build a clean, simple internal analytics workspace. Prioritise usability and explainability over visual complexity.

### 7.1 Navigation

Provide these primary pages:

1. **Overview dashboard**
   - Total feedback records processed.
   - Number of distinct canonical customer problems.
   - Top problem themes by evidence volume.
   - Feedback trends by week/month.
   - Sentiment distribution by journey/module.
   - Processing run status and last successful run.
   - Filters for date range, source, platform and journey.

2. **Customer problem explorer**
   - Search/filter canonical problems.
   - Sort by frequency, severity signal, trend and review status.
   - View problem statement, intent, aspect and journey mapping.
   - View supporting feedback snippets and evidence spans.
   - Show cluster membership, source distribution and time trend.
   - Allow authorised reviewers to accept, merge, split, rename or reject clusters and mappings.
   - Clearly label unmapped/new category proposals.

3. **Journey explorer**
   - Expandable taxonomy tree.
   - Problem count and evidence volume by module/feature/stage.
   - Drill down from journey node to canonical problems and evidence.

4. **Backlog upload and validation**
   - Upload a CSV and display a downloadable CSV template.
   - Validate columns and show row-level upload errors before processing.
   - Show workflow status and progress by stage.
   - Do not block the browser while batch jobs run; poll a status API or use server-sent events if appropriate.

5. **Backlog validation report**
   - Backlog-by-backlog alignment summary.
   - Matching problem/evidence matrix.
   - Strong/partial/weak/unsupported relationships.
   - Acceptance-criteria gaps.
   - High-evidence customer problems not covered.
   - Evidence drill-down to redacted comments.
   - Download report as JSON and CSV; PDF is optional.
   - PO reviewer action: accept recommendation, disagree, or mark for further investigation, with an audit note.

6. **Pipeline runs / admin**
   - Source GCS URI and generation.
   - Run IDs and stage status.
   - Accepted/rejected record counts.
   - Model/taxonomy versions.
   - Errors with safe, non-PII messages.

### 7.2 UI behaviour

- The frontend must call the backend API only; do not put GCP service-account credentials in the browser.
- Every chart must be driven by BigQuery-derived backend data, not hardcoded demo values.
- Add loading, empty, partial-failure and error states.
- Make filters consistent across pages.
- Clicking any problem or validation finding must open the supporting evidence.
- Use clear labels that distinguish customer feedback volume from unique customers and from total banking-app users.
- Provide a persistent synthetic-data warning when the supplied sample dataset is loaded.

## 8. Core API contracts

Implement versioned REST APIs under `/api/v1` at minimum:

### Feedback pipeline

- `POST /feedback-pipelines` — start a pipeline using a GCS URI and optional object generation.
- `GET /feedback-pipelines/{run_id}` — run status and stage statuses.
- `GET /feedback-pipelines` — list recent runs.
- `GET /feedback/summary` — dashboard aggregate metrics.
- `GET /problems` — paginated/filterable canonical problems.
- `GET /problems/{problem_id}` — problem details and supporting evidence.
- `POST /problems/{problem_id}/review` — submit an auditable review decision.
- `GET /taxonomy` — retrieve taxonomy tree and version.
- `GET /taxonomy/proposals` — retrieve proposed categories.

### Backlog validation

- `POST /backlog-uploads` — accept multipart CSV, validate it and store it in GCS.
- `GET /backlog-uploads/{upload_id}` — upload validation status.
- `POST /backlog-uploads/{upload_id}/validate` — start Module G workflow.
- `GET /backlog-validation-runs/{run_id}` — processing status.
- `GET /backlog-validation-reports/{report_id}` — complete report.
- `GET /backlog-validation-reports/{report_id}/download` — downloadable JSON/CSV report.
- `POST /backlog-validation-reports/{report_id}/review` — PO review decision and note.

Use OpenAPI documentation generated by FastAPI. Use pagination and filter parameters. Add idempotency keys to job-start endpoints. Return a `202 Accepted` response with a run ID for asynchronous work.

## 9. Reliability, idempotency and observability

- Every pipeline has a unique `run_id`, `tenant_id` (even if one tenant is used in the PoV), `input_uri`, `input_generation`, `code_version`, `schema_version`, `model_version`, `taxonomy_version`, start/end timestamps and status.
- Make each stage idempotent. Use BigQuery `MERGE`/stable keys or run-scoped staging followed by atomic publication.
- Do not expose partially processed records as a completed analytics snapshot. Publish a run only after required stages pass validation.
- Retry transient GCS, BigQuery and model API errors with bounded exponential backoff and jitter. Do not retry permanent schema/validation failures endlessly.
- Use dead-letter/error tables for failed rows and model calls.
- Track per-stage records processed, successes, failures, latency, token usage/cost where applicable and retry counts.
- Include correlation IDs in API responses and structured logs.
- Avoid logging raw comments, account-like patterns, access tokens or secrets.
- Support cancellation or safe termination of long-running workflows.

## 10. Security, privacy and governance

Even synthetic PoV data must be handled as though it could later be replaced with real bank feedback.

- Use least-privilege service accounts for frontend, backend, ingestion jobs, model inference and deployment.
- Store secrets in Secret Manager.
- Encrypt transport and storage using GCP-managed encryption by default; document optional CMEK where enterprise policy requires it.
- Redact PII before model inference and before data is exposed in the UI.
- Keep raw source object permissions separate from analytics table permissions.
- Restrict access to raw comments; most users should see redacted excerpts and aggregate evidence.
- Add role-based access for administrator, customer journey expert, product owner and read-only analyst.
- Use IAP or an approved managed identity solution for internal PoV access; do not implement insecure custom password storage.
- Add audit records for data uploads, pipeline runs, review actions, taxonomy changes and report downloads.
- Support configurable retention and deletion policies.
- Never train an external provider model on customer feedback unless the bank explicitly authorises it.

## 11. Testing and evaluation requirements

Create automated tests and an evaluation harness before claiming model quality.

### Software tests

- Unit tests for CSV parsing, validation, PII redaction, segmentation, schema validation, idempotency, taxonomy mapping and backlog evaluation.
- Integration tests for GCS, BigQuery and Workflows using mocks/emulators where practical; provide a separate opt-in GCP integration test suite.
- Contract tests for every module input/output schema.
- API tests for upload, job creation, polling and report access.
- Frontend tests for key flows and error states.
- Security tests for auth boundaries, file size/type checks, CSV injection and unsafe evidence rendering.

### NLP/decision evaluation

Create a human-annotated benchmark split, even if it begins with a smaller sample. Evaluate:

- intent classification precision/recall/F1;
- problem extraction evidence-span precision/recall;
- aspect-level sentiment F1;
- journey mapping top-1 and hierarchical accuracy;
- semantic retrieval Recall@K / nDCG;
- cluster coherence and human agreement;
- cluster-label faithfulness to source evidence;
- backlog-problem relationship precision/recall and reviewer agreement;
- percentage of validation statements with valid supporting feedback evidence.

Prioritise precision for the claim that a backlog addresses a problem. An uncertain relationship must become `NEEDS_REVIEW`, not a confident positive. Do not use the same LLM outputs as both predictions and ground truth.

## 12. Deployment and developer experience

Provide:

1. `README.md` with architecture, prerequisites, local run, GCP setup, data flow, API documentation, troubleshooting and teardown instructions.
2. `.env.example` with placeholder values only.
3. Dockerfiles and `docker-compose.yml` for local development using local/mock storage and model adapters.
4. Cloud Build configuration to test, build, push to Artifact Registry and deploy.
5. Terraform modules or clear `gcloud` scripts for enabling required APIs, creating buckets/datasets/service accounts, assigning IAM, deploying Cloud Run resources, deploying Workflows and configuring triggers.
6. SQL migrations to create BigQuery datasets/tables/views.
7. A sample command to upload the supplied synthetic CSV to GCS and run the feedback pipeline.
8. A sample backlog CSV template and a small sample backlog file for testing.
9. A command to run unit tests and a separate command to run GCP integration tests.
10. A teardown guide to prevent unused resources and costs.

Use placeholders like `<PROJECT_ID>`, `<REGION>`, `<FEEDBACK_BUCKET>`, `<BQ_DATASET>` and `<ARTIFACT_REGISTRY_REPOSITORY>`. Do not invent or commit the user's project identifiers.

## 13. Implementation order

Implement in small, testable increments. Do not produce a huge untested code dump.

**Milestone 1 — Foundation:** repository, typed settings, Docker, local Compose, FastAPI health route, frontend shell, BigQuery schema/migrations, GCS/BigQuery adapters and test harness.

**Milestone 2 — Module A:** GCS source read, CSV validation, checksum/manifest, redaction, deduplication, curated BigQuery writes and idempotency tests.

**Milestone 3 — Module B:** extraction provider interface, structured extraction contract, model adapter, evidence span validation, retry/dead-letter handling and benchmark evaluation.

**Milestone 4 — Modules C-E:** embeddings, clustering, canonical problem repository, hybrid taxonomy mapping, human review states, BigQuery analytics views and problem explorer.

**Milestone 5 — Modules F-G:** backlog CSV upload to GCS, validation, candidate problem retrieval, structured alignment evaluation, report persistence and report UI.

**Milestone 6 — GCP deployment:** Artifact Registry, Cloud Run services/jobs, Vertex AI access, Workflows, IAM, Cloud Build and end-to-end GCP smoke test.

At each milestone: run tests, update README, provide a concise architecture/implementation note and ensure the repository remains runnable. If credentials or GCP project access are unavailable, complete the code and provide exact deployment instructions; do not claim that cloud resources were deployed.

## 14. Acceptance criteria

The PoV is complete only when all of the following work end to end:

1. The supplied synthetic feedback CSV can be uploaded to or copied into GCS and is retained as the source-of-truth object.
2. A user can start a feedback pipeline from the UI using the GCS object URI (or an automatic trigger can start it).
3. Module A reads the exact GCS object generation, validates it and writes a manifest plus curated feedback to BigQuery.
4. Modules B-D create structured insights, canonical problems and hybrid banking journey mappings with exact evidence references.
5. Module E publishes dashboard-ready BigQuery tables/views and records the completed pipeline run.
6. The UI displays actual BigQuery-derived metrics and permits drill-down to redacted feedback evidence.
7. A PO can upload a backlog CSV through the UI; the object is stored in GCS and its rows are validated.
8. Module G evaluates the backlog items against canonical customer problems and supporting feedback evidence.
9. The PO can view a report showing strong, partial, weak, unsupported or needs-review relationships, coverage gaps and acceptance-criteria gaps.
10. The report can be downloaded and every substantive conclusion is traceable to feedback and model/taxonomy versions.
11. A repeated run on the same source object generation is idempotent and does not duplicate data.
12. The solution runs locally in Docker Compose with mock adapters and can be deployed to GCP with documented commands/IaC.
13. Tests pass, no secrets are committed, and the UI visibly labels the sample feedback as synthetic.

## 15. Required response and deliverables from the coding agent

Before coding, provide a concise implementation plan and a diagram. Then implement the application, not just the plan. Deliver:

- complete source code;
- frontend and backend Dockerfiles;
- batch worker Dockerfile;
- local Docker Compose configuration;
- GCP Workflows definitions;
- BigQuery SQL schema/migrations/views;
- taxonomy file;
- model adapter interfaces and working PoV adapter;
- feedback pipeline Modules A-E;
- backlog pipeline Modules F-G;
- API and UI;
- tests and evaluation harness;
- deployment/IaC scripts;
- README and sample CSV templates.

For every external model dependency, explain the chosen model, data handling, cost considerations, latency trade-offs and how to replace it. Prefer deterministic code for validation, aggregation, joins, thresholds and database writes; use LLMs only for language tasks that genuinely require semantic interpretation.

Do not claim that the application is production-ready merely because it runs. Clearly mark PoV shortcuts, limitations, unvalidated model metrics, security assumptions and tasks required before processing real banking customer data.
