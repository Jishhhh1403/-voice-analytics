# GCP migration runbook

This document describes the gap between the local-first PoV and the target GCP architecture from `banking_customer_intelligence_gcp_build_prompt.md`. The repository contains deployment scaffolding and a read-only BigQuery analytics adapter, but **no cloud resources were deployed**. Treat the Terraform, Workflows, Cloud Build and BigQuery adapter assets as migration-ready scaffolding, not as proof of a cloud deployment.

## Target architecture

```text
Browser
  -> Cloud Run frontend
  -> Cloud Run FastAPI backend (only service allowed to query BigQuery)
  -> Cloud Workflows
  -> Cloud Run Jobs (Modules A-E and F-G)
  -> Vertex AI Gemini (optional extraction/embeddings)
  -> BigQuery (analytics) + GCS (immutable source objects)
```

## Current status

| Area | Local PoV | GCP target | Status |
| --- | --- | --- | --- |
| Raw feedback | Local immutable object store (`data/local/objects`) | GCS with object versioning | GCS adapter exists; not integration-tested |
| Analytics store | SQLite (`data/local/bci.db`) | BigQuery datasets/tables/views | Read-only adapter scaffolded in `backend/app/analytics/`; SQLite remains the write store. DDL 001 + 002 added. |
| Pipeline orchestration | In-process threads | Cloud Workflows + Cloud Run Jobs | Workflows YAML and worker CLI added; worker still runs whole pipeline |
| Extraction | Deterministic `rules-v1` | Rules + optional Gemini/OpenAI-compatible | Provider adapter exists |
| Embeddings | TF-IDF + SVD | Local, sentence-transformers, Gemini or Vertex embeddings | Adapters exist with deterministic fallback |
| Frontend | Vite dev / nginx | Cloud Run + nginx | Container image added; `BACKEND_URL` templated |
| Backend | FastAPI + SQLite | Cloud Run + BigQuery | Cloud Run image added; BigQuery gap remains |
| Secrets | `.env` locally | Secret Manager | Secret resource added; no version created |
| Auth | No authentication | IAM + application roles | **Missing** |
| Observability | JSON logs | Cloud Logging/Monitoring | Logs ready; metrics/alerts partial |
| Tests | 20 pytest tests pass | Unit + integration + contract | GCP integration/contract tests missing |

## Blocking work before a real GCP deployment

1. **Complete the BigQuery write path.** `backend/app/analytics/` now defines a read interface, a SQLite implementation and a read-only BigQuery implementation. The operational `Repository` in `backend/app/repository.py` remains SQLite-specific. Production still needs durable writes for `create_run`, `stage`, `save_feedback`, `save_quarantine`, `save_run_insights`, `save_problems`, `replace_evidence`, measurement/priority snapshots, backlog uploads, validation reports and audit log. Use parameterised queries and explicit columns; never `SELECT *` for production reads. Set `ANALYTICS_BACKEND=bigquery`, `BIGQUERY_PROJECT` and `BIGQUERY_DATASET_PREFIX` to enable the read adapter.
2. **Persist shared run state between jobs.** Cloud Run Jobs do not share local SQLite. Until BigQuery state is shared, the Workflows stage calls cannot be independent. The current worker makes the first call perform the full pipeline and later calls reuse the completed run, which preserves the stage contract but does not split the work.
3. **Backend authentication/authorisation.** Review endpoints currently trust a `reviewer` field in the request body. Add an identity provider (IAP or Firebase Auth) and enforce `REVIEW_ROLES`. Never expose raw evidence to unauthorised users.
4. **Durable uploads and reports.** Ensure backlog uploads and generated report exports are written to GCS under `backlogs/uploads/<tenant>/<upload_id>/` and `reports/`, and that report downloads stream from GCS rather than local disk.
5. **Retry, dead-letter and cancellation.** Add bounded exponential backoff with jitter for GCS, BigQuery and model calls; write permanent failures to a dead-letter table; expose cancellation for long runs.
6. **Secret Manager wiring.** Create a version for `bci-gemini-api-key` and mount it with `--set-secrets`; the Terraform secret resource intentionally has no version.
7. **Frontend/backend URL wiring.** `docker/nginx.conf` proxies `/api/` to `${BACKEND_URL}`. Compose sets `http://backend:8000`; Cloud Build resolves the deployed backend URL. Confirm CORS and cookies for the final hostnames.
8. **SQLite persistence caveat.** `cloudbuild.yaml` sets `DATA_DIR=/tmp/bci`. Cloud Run local disk is ephemeral. Do not use this deployment for retention until BigQuery is implemented.

## Provisioning

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars
# edit project_id and feedback_bucket_name
terraform init
terraform apply
```

Terraform creates:

- enabled APIs
- versioned GCS bucket
- BigQuery datasets: `ops`, `staging`, `curated`, `intelligence`, `taxonomy`, `backlog`, `validation`
- Artifact Registry repository
- service accounts and least-privilege project roles for backend, worker and Workflows
- optional Cloud Run backend/frontend services and worker job (only when image variables are set)
- Secret Manager secret placeholder
- two Workflows definitions

Terraform does not create BigQuery tables/views; apply them with `scripts/gcp_sql.sh`.

## Build and deploy

```bash
PROJECT_ID=<PROJECT_ID> \
FEEDBACK_BUCKET=<FEEDBACK_BUCKET> \
REGION=us-central1 \
./scripts/gcp_deploy.sh
```

This runs Terraform, then `gcloud builds submit` using `cloudbuild.yaml` (tests, frontend build, three image builds/pushes, Cloud Run deploys, Workflows deploys), then applies SQL.

Images:

- `${REGION}-docker.pkg.dev/${PROJECT_ID}/bci/bci-backend`
- `${REGION}-docker.pkg.dev/${PROJECT_ID}/bci/bci-frontend`
- `${REGION}-docker.pkg.dev/${PROJECT_ID}/bci/bci-worker`

## Upload and run

```bash
PROJECT_ID=<PROJECT_ID> FEEDBACK_BUCKET=<FEEDBACK_BUCKET> ./scripts/gcp_upload_and_run.sh
```

The script uploads `synthetic_banking_app_feedback_15000.csv`, captures the object generation, and runs the feedback Workflow with `run_id`, `input_uri` and `generation`. The Workflow calls the worker job once per stage; the worker reuses the completed run after the first stage.

## SQL files

- `sql/migrations/001_bigquery_schema.sql` - base datasets' tables, partitions and clusters.
- `sql/migrations/002_bigquery_schema_enhancements.sql` - Module A-G additive columns and new tables for duplicates, data quality, measurement, prioritisation, model execution and backlog coverage.
- `sql/migrations/003_bigquery_mds.sql` - MDS theme-map vectors, runs, points and neighbour tables.
- `sql/migrations/004_bigquery_problem_dimensions.sql` - exploratory FAMD feature snapshots, runs, scores, definitions, contributions, memberships, trends and publications.
- `sql/migrations/005_bigquery_problem_dimension_coefficients.sql` - signed FAMD coefficients, factor metadata and equations.
- `sql/migrations/006_bigquery_problem_portfolio.sql` - portfolio runs, factor nomenclature/profiles, serializations, narratives and validation.
- `sql/views/001_dashboard_views.sql` - problem overview, journey summary, sentiment daily, report findings, relationship distribution, run health.

Run manually:

```bash
PROJECT_ID=<PROJECT_ID> REGION=us-central1 ./scripts/gcp_sql.sh
```

## Workflows

- `workflows/feedback_pipeline.yaml` - stages `validate_source -> module_a_ingest -> module_b_extract -> module_c_discover -> module_d_map -> measurement_engine -> priority_engine -> module_e_publish -> mark_run_complete`.
- `workflows/backlog_validation.yaml` - stages `module_f_normalise -> module_g_validate`.

Both use `googleapis.run.v1.namespaces.jobs.run` and poll the operation. Input parameters: `region`, `worker_job`, `run_id`/`upload_id`, and so on.

## Teardown

Review resources, then:

```bash
FORCE=1 PROJECT_ID=<PROJECT_ID> REGION=us-central1 FEEDBACK_BUCKET=<FEEDBACK_BUCKET> ./scripts/gcp_teardown.sh
```

This deletes Cloud Run services/jobs, Workflows, BigQuery datasets (with contents), the bucket, Artifact Registry repository and service accounts. Verify in the console afterwards. If you used Terraform state, run `terraform destroy` too, after deleting BigQuery contents (datasets are configured with `delete_contents_on_destroy = false`).

## Frontend lint setup

`npm run lint` currently fails because no ESLint configuration is committed. Add one of:

```bash
cd frontend
npm install --save-dev eslint@8 @typescript-eslint/parser @typescript-eslint/eslint-plugin \
  eslint-plugin-react-hooks eslint-plugin-react-refresh
```

Then add `frontend/.eslintrc.cjs` extending `eslint:recommended`, `plugin:@typescript-eslint/recommended` and `plugin:react-hooks/recommended`, with `parserOptions.project` pointing at `tsconfig.json`. Keep `npm run build` (tsc + Vite) as the required gate until lint is configured.

## Security notes

- Never commit `.env`, API keys or service-account keys.
- Use attached service identities / ADC; do not create key files.
- Redact PII before extraction and before evidence is returned by the API.
- Keep raw GCS object permissions separate from analytics table permissions.
- Restrict `allUsers` invoker bindings created by the PoV Terraform before production use.

## Measurement and prioritisation in GCP

The measurement and priority engineers write to `problem_metrics_daily`, `problem_measurement_snapshots`, `problem_priority_snapshots` and `scoring_methodology_versions`. Every snapshot carries a status and methodology version. When migrating to BigQuery, preserve `NO_DATA`/`INSUFFICIENT_DATA` rows rather than coalescing them to zero, and keep the scoring methodology version attached to each priority row.

## Guarded advanced analytics

Survival and conjoint analyses remain disabled by default (`ENABLE_SURVIVAL_ANALYSIS=false`, `ENABLE_CONJOINT_ANALYSIS=false`). Their result tables are created by migration 002, but the functions return `NOT_AVAILABLE`/`NOT_APPLICABLE` until event/censoring data or a controlled experimental design is supplied.
