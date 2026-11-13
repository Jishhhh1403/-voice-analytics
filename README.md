# Banking Customer Intelligence & Backlog Validation

Local-first PoV that turns unstructured banking-app customer feedback into evidence-backed customer problems, maps them to a banking journey taxonomy, and validates whether backlog items address the strongest customer evidence.

> The bundled dataset (`synthetic_banking_app_feedback_15000.csv`) is synthetic and generated for software testing. It is not real customer feedback and is not representative of any bank. The UI keeps this warning visible.

## What is implemented

- **Feedback pipeline (Modules A-E)** - ingestion, Presidio/regex PII redaction, language detection, validation/quarantine, data-quality checks, exact/near/repeat duplicate linking (never discarding complaints), immutable object generations, multi-intent/aspect/symptom extraction, sentiment, configurable embeddings, canonical problem discovery, hybrid taxonomy mapping, measurement and prioritisation, MDS theme mapping, publication.
- **Problem dimensions (FAMD)** - an auditable, additive layer over canonical problems: versioned features, data-quality gates, missing-data-aware FAMD, optional bootstrap stability and EFA comparison, analyst review/rename/reject gates, immutable publication with republish/rollback, run-specific and latest-published read models, plus signed problem-factor coefficients, squared-coordinate shares and readable equations. Optional structured LLM nomenclature reads one complete factor equation per retained factor with banking taxonomy context and proposes reviewable business names; there are no deterministic factor-name fallbacks. Quota-limited Gemini can be replaced or supplemented by any OpenAI-compatible endpoint. It never changes canonical problems, priorities, MDS coordinates or FAMD statistics.
- **Narrative serialization** - all identified problems and factor coefficients for a factor-analysis run; one LangChain agent names and describes every retained factor from all problem equations and the banking taxonomy. Deterministic FAMD metrics are merged into the narrative, approved names are preserved, and results are persisted. The LLM never becomes the source of truth. The deterministic portfolio-run serialization and Gemini narrative APIs remain available.
- **Backlog validation (Modules F-G)** - CSV upload, optional richer profile columns, normalisation, row quarantine, hybrid dense+sparse candidate retrieval, relationship/alignment scoring, explainable findings, coverage matrix, acceptance-criteria gaps, report review and CSV/JSON download. The validator never auto-approves or auto-rejects a backlog.
- **API** - FastAPI with typed settings, structured JSON logs, correlation IDs, idempotency keys, audit trail and run/stage tracking.
- **UI** - React + TypeScript: Journey explorer, Customer problems, Theme map, Problem dimensions, Narrative serialization, Problem detail with per-evidence signals, impact measurement and published dimension membership, Backlog validation, Validation report.
- **Runtime** - SQLite + filesystem immutable object store locally; GCS object-store adapter; optional Gemini/OpenAI-compatible extraction and Gemini embeddings.
- **Delivery** - backend, frontend and batch-worker Dockerfiles, local Docker Compose, tests, and GCP migration scaffolding (SQL, Workflows, Terraform, Cloud Build, scripts).

The local PoV uses SQLite for analytics. BigQuery is the target production analytics store; see [docs/gcp-migration.md](docs/gcp-migration.md) for the exact remaining migration work.

## Documentation

- [Pipeline algorithms](docs/pipeline-algorithms.md) - stage-by-stage algorithm implementation details.
- [Algorithms and UI calculations](docs/algorithms-and-ui-calculations.md) - how every active UI value is calculated.
- [Narrative serialization](docs/problem_portfolio.md) - all-problem coefficient matrix, LangChain factor narrative agent, deterministic portfolio serialization, validation and regeneration.
- [LLM factor interpretation](docs/problem_dimension_interpretation.md) - factor-equation nomenclature, taxonomy context, provider fallback, persistence and review behavior.

## Architecture

```text
Browser
  -> Nginx / Vite frontend
  -> FastAPI backend (only service allowed to touch storage/analytics)
       -> Object store (local filesystem now, GCS adapter available)
       -> Analytics store (SQLite now, BigQuery target)
       -> Intelligence layer (rules-v1 now, optional Gemini/OpenAI-compatible)
       -> Feedback pipeline: validate_source -> ingest -> extract -> discover -> map -> measurement -> prioritisation -> publish
       -> Backlog pipeline: normalise -> hybrid validate -> coverage -> report
```

Data flow:

```text
feedback CSV object -> Module A ingest -> curated feedback
curated feedback -> Modules B/C/D -> insights -> canonical problems -> taxonomy mappings
canonical problems + backlog CSV -> Module G -> validation report -> UI/CSV/JSON
```

## Prerequisites

- Python 3.11+ (3.13 tested)
- Node.js 20+ and npm
- Docker 24+ with Compose v2 (optional, for containerised run)

## Local run

```bash
cp .env.example .env
make install
make test
make dev-backend    # terminal 1: http://127.0.0.1:8000 (docs at /docs)
make dev-frontend   # terminal 2: http://127.0.0.1:5173
```

On first backend startup the sample feedback source is seeded and a feedback pipeline is started automatically. Disable with `AUTO_SEED_SOURCE=false` and `AUTO_RUN_SAMPLE=false`.

Run the batch worker directly:

```bash
PYTHONPATH=backend python -m pipelines.jobs.run_pipeline --force
PYTHONPATH=backend python -m pipelines.jobs.run_pipeline --mode dimensions --feedback-run-id RUN-...
```

## Docker Compose

```bash
cp .env.example .env
make docker-up      # frontend http://localhost:8080, backend http://localhost:8000
make docker-down    # stops and removes the data volume
```

`docker compose config` is valid. The worker image is defined in `docker/Dockerfile.worker` and is intended for Cloud Run Jobs; see the GCP runbook.

## API

All routes are under `/api/v1`. Interactive docs: `/docs`.

| Area | Endpoints |
| --- | --- |
| Health/meta | `GET /health`, `GET /meta/source` |
| Feedback pipeline | `GET/POST /feedback-sources`, `POST /feedback-pipelines`, `GET /feedback-pipelines`, `GET /feedback-pipelines/{run_id}` |
| Analytics | `GET /feedback/summary`, `GET /feedback/options`, `GET /problems`, `GET /problems/{problem_id}`, `GET /priorities`, `GET /problems/{problem_id}/priority`, `GET /problems/{problem_id}/measurement` |
| Theme map | `GET /problem-map`, `POST /problem-map/recompute`, `GET /problem-map/{problem_id}` |
| Problem dimensions | `GET /problem-dimensions/status`, `POST /problem-dimensions/runs`, `GET /problem-dimensions/runs`, `GET /problem-dimensions/runs/{run_id}`, `GET /problem-dimensions/runs/{run_id}/dimensions/{dimension_id}`, `GET /problem-dimensions/runs/{run_id}/problems/{problem_id}`, `GET /problem-dimensions/runs/{run_id}/problems/{problem_id}/profile`, `GET /problem-dimensions/runs/{run_id}/coefficients`, `GET /problem-dimensions/runs/{run_id}/coefficients.csv`, `GET /problem-dimensions/runs/{run_id}/variables`, `GET /problem-dimensions/runs/{run_id}/interpretation`, `GET /problem-dimensions/runs/{run_id}/dimensions/{dimension_id}/interpretation`, `POST /problem-dimensions/runs/{run_id}/interpretation/regenerate`, `GET /problem-dimensions/latest`, `GET /problem-dimensions/latest/dimensions/{dimension_id}`, `GET /problem-dimensions/latest/problems/{problem_id}`, `POST /problem-dimensions/runs/{run_id}/dimensions/{dimension_id}/review`, `POST /problem-dimensions/runs/{run_id}/publish` |
| Factor analysis alias | `GET /factor-analysis/status`, `POST /factor-analysis/runs`, `GET /factor-analysis/runs`, `GET /factor-analysis/runs/{run_id}`, `GET /factor-analysis/runs/{run_id}/coefficients`, `GET /factor-analysis/runs/{run_id}/variables`, `GET /factor-analysis/runs/{run_id}/problems/{problem_id}` |
| Quality/evidence | `GET /data-quality`, `GET /duplicates`, `GET /diagnostics`, `GET /problem-relationships` |
| Review | `POST /problems/{problem_id}/review`, `POST /taxonomy/proposals/{id}/review`, `POST /backlog-validation-reports/{id}/review` |
| Journey/taxonomy | `GET /taxonomy`, `GET /taxonomy/proposals`, `GET /journey` |
| Backlog | `GET /backlog-template`, `GET/POST /backlog-uploads`, `POST /backlog-uploads/sample`, `POST /backlog-uploads/{id}/validate` |
| Reports | `GET /backlog-validation-runs/{run_id}`, `GET /backlog-validation-reports`, `GET /backlog-validation-reports/{id}`, `GET /backlog-validation-reports/{id}/coverage`, `GET /backlog-validation-reports/{id}/download?format=csv|json` |
| Admin | `GET /admin/overview` |

Idempotency: pass `Idempotency-Key` on pipeline/validation start requests to make retries safe.

## Data and configuration

- `synthetic_banking_app_feedback_15000.csv` - primary synthetic feedback dataset (15,000 rows, covers all 62 taxonomy feature nodes).
- `synthetic_banking_app_feedback_1800.csv` - smaller synthetic fixture (1,800 rows) kept for quick local runs.
- `sample_backlog_upload.csv` - sample backlog for validation.
- `taxonomy/banking_taxonomy_v1.yaml` - versioned banking journey taxonomy.
- `data/local/` - local SQLite database and immutable object store. Runtime data is gitignored.
- `.env.example` - every supported setting with placeholders; no secrets committed.

Provider modes:

- `EXTRACTION_PROVIDER=rules` (default, deterministic, no API key)
- `EXTRACTION_PROVIDER=gemini` with `GEMINI_API_KEY`
- `EXTRACTION_PROVIDER=openai_compatible` with `OPENAI_BASE_URL`/`OPENAI_MODEL` (for example Ollama)
- `PROBLEM_DIMENSION_LLM_PROVIDER=gemini`, `openai_compatible` or `auto`; `PROBLEM_DIMENSION_LLM_FALLBACK_PROVIDER` enables automatic fallback
- `EMBEDDING_PROVIDER=local` (TF-IDF + SVD), `sentence_transformer`, `gemini` or `vertex`
- `PII_PROVIDER=regex`, `presidio` or `hybrid` (Presidio is optional; any failure falls back to regex)
- `LANGUAGE_DETECTION_PROVIDER=heuristic`, `langdetect` or `fasttext`
- `ANALYTICS_BACKEND=sqlite` (default) or `bigquery` (read-only adapter; SQLite remains the write store)

## Testing

```bash
make test                 # pytest: ingestion, intelligence modules, pipeline, API, backlog/report
cd frontend && npm run build
```

`make lint` runs Ruff and ESLint. Ruff is configured in `pyproject.toml`; install frontend ESLint config dependencies as described in `docs/gcp-migration.md` before running `npm run lint`.

## GCP deployment

The repository contains migration assets under:

- `sql/migrations/` - BigQuery datasets/tables
- `sql/views/` - dashboard views
- `workflows/` - Cloud Workflows stage definitions
- `infra/terraform/` - APIs, buckets, BigQuery, IAM, Artifact Registry, Cloud Run services/jobs
- `cloudbuild.yaml` - build/test/push/deploy pipeline
- `scripts/` - deploy and teardown helpers

Read [docs/gcp-migration.md](docs/gcp-migration.md) before deploying. **No cloud resources were deployed as part of this PoV.** Do not claim deployment without running the steps against a real project.

## Troubleshooting

- **Port already in use** - stop the existing backend/frontend process or change ports.
- **`app` module not found** - run backend commands with `PYTHONPATH=backend` or use `--app-dir backend`.
- **Pipeline fails at startup** - inspect structured logs; the run and stage error are visible in `/api/v1/admin/overview` and the Runs page.
- **No problems in UI** - wait for the first pipeline to finish, or start one from Overview; confirm `/api/v1/meta/source` reports a completed run.
- **Backlog report has no findings** - confirm the upload is validated and a completed feedback run exists.
- **GCS errors locally** - leave `OBJECT_STORE=local`; GCS requires ADC and `GCS_BUCKET`.

## Teardown

- Local: `make docker-down` (removes the data volume) or delete `data/local/`.
- GCP: follow `scripts/gcp_teardown.sh` and the teardown section of `docs/gcp-migration.md` to remove Cloud Run services/jobs, Workflows, buckets, datasets, Artifact Registry images and service accounts.


source .venv/bin/activate
PYTHONPATH=backend python -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000