# Banking Customer Intelligence & Backlog Validation

## End-to-End Project Guide

> **Project:** `voice-analytics`  
> **Document scope:** entire repository, including backend, frontend, pipelines, analytics, taxonomy, tests, infrastructure and supporting documents.  
> **Document basis:** the implementation in this workspace, not only the README. Where repository documents and code disagree, this guide describes the current code in `frontend/src/App.tsx`, `backend/app/**`, `pipelines/**`, `tests/**` and `sql/**`.

> **Synthetic-data warning:** the bundled dataset `synthetic_banking_app_feedback_15000.csv` is synthetic. It was generated for software testing and proof-of-value development by `scripts/generate_feedback_dataset.py`. It is not real customer feedback and is not representative of any bank. The UI deliberately keeps this warning visible.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Business Context and Purpose](#2-business-context-and-purpose)
3. [What the System Does](#3-what-the-system-does)
4. [Key Concepts and Glossary](#4-key-concepts-and-glossary)
5. [System Architecture](#5-system-architecture)
6. [Repository Map](#6-repository-map)
7. [End-to-End Data Flows](#7-end-to-end-data-flows)
8. [Feedback Pipeline: Modules A-E](#8-feedback-pipeline-modules-a-e)
9. [Measurement and Problem Prioritisation](#9-measurement-and-problem-prioritisation)
10. [MDS Theme Map](#10-mds-theme-map)
11. [Problem Dimensions: The FAMD Layer](#11-problem-dimensions-the-famd-layer)
12. [Factor Evidence Prioritisation](#12-factor-evidence-prioritisation)
13. [Factor Naming, Narrative Serialization and Portfolio Narrative](#13-factor-naming-narrative-serialization-and-portfolio-narrative)
14. [Evidence Mapping Graph](#14-evidence-mapping-graph)
15. [Backlog Validation: Modules F-G](#15-backlog-validation-modules-f-g)
16. [API Reference](#16-api-reference)
17. [Frontend Application](#17-frontend-application)
18. [Data Model and Persistence](#18-data-model-and-persistence)
19. [Configuration](#19-configuration)
20. [Running the Project](#20-running-the-project)
21. [Testing and Quality Gates](#21-testing-and-quality-gates)
22. [Docker and GCP Deployment Assets](#22-docker-and-gcp-deployment-assets)
23. [Security, Privacy and Governance](#23-security-privacy-and-governance)
24. [Limitations and Non-Goals](#24-limitations-and-non-goals)
25. [Troubleshooting](#25-troubleshooting)
26. [File-by-File Guide](#26-file-by-file-guide)
27. [Suggested Reading Path](#27-suggested-reading-path)

---

## 1. Executive Summary

This repository is a **local-first proof-of-value (PoV) platform** for banking customer-experience analytics. It converts unstructured banking-app feedback into:

1. **Redacted, validated and traceable feedback records.**
2. **Structured customer insights** such as intent, aspect, symptom, sentiment, emotion, effort and outcome.
3. **Canonical customer problems** discovered by grouping similar evidence.
4. **Mappings to a versioned banking-app taxonomy.**
5. **Windowed measurements and a transparent priority score** for each problem.
6. **A two-dimensional semantic theme map** built with multidimensional scaling (MDS).
7. **Exploratory customer-problem factors** discovered with factor analysis of mixed data (FAMD), including signed coefficients, readable equations and analyst review.
8. **A deterministic factor evidence priority ranking** based on prevalence, statistical importance, problem representation and semantic coherence.
9. **LLM-assisted factor names and narratives**, constrained by deterministic evidence and validation.
10. **A backlog validation report** that tests whether backlog items actually address the strongest customer evidence.

The system is intentionally **evidence-first**:

- Missing data stays missing; it is never silently converted to zero.
- LLM output is optional and never becomes the source of statistical truth.
- FAMD coefficients are described as associations, not causes.
- MDS position means semantic similarity, not severity.
- Backlog validation never auto-approves or auto-rejects work.
- Human review is required before factor publication by default.
- Every run, stage, review decision and publication is persisted and auditable.

**Current production status:** the application runs locally with SQLite and a filesystem object store. Docker Compose and substantial GCP migration assets exist, but **no cloud resources were deployed as part of this PoV**. The BigQuery adapter is read-only; SQLite remains the write store.

---

## 2. Business Context and Purpose

### 2.1 The business problem

Banks receive customer feedback through app-store reviews, in-app feedback, surveys, complaint portals and support chats. The feedback is usually:

- unstructured and written in different styles;
- duplicated, repeated or near-duplicated;
- mixed across multiple issues in one comment;
- noisy, emotional and sometimes contains personal data;
- difficult to connect to product, journey or backlog decisions.

A product owner can therefore end up prioritising the loudest complaint rather than the best-evidenced customer problem. Backlog items may also be written in delivery language that does not obviously match customer language, making it hard to know whether work addresses the strongest evidence.

### 2.2 The questions the system answers

- What are customers actually struggling with?
- How much evidence supports each problem?
- Which banking journey, feature or app area is involved?
- Is the problem growing, shrinking or stable?
- Which problems have the strongest combination of customer impact, risk indicator, operational impact, trend and strategic fit?
- What broader latent themes or factors connect otherwise separate problems?
- Which factors are broad, statistically important and semantically coherent?
- Are factor names defensible to a business audience?
- Which backlog items genuinely address the highest-priority customer evidence?
- Which high-priority factors or high-evidence problems have no backlog coverage?
- What can and cannot be concluded from the data?

### 2.3 Intended users

| User | Main value |
| --- | --- |
| Product owner / backlog owner | Compare backlog coverage against prioritised customer evidence. |
| Customer-experience analyst | Inspect evidence, themes, journey coverage and problem detail. |
| Data scientist / analytics engineer | Audit algorithms, coefficients, publications and model versions. |
| Journey or domain expert | Review taxonomy mappings and factor names. |
| Risk / compliance reviewer | See what is evidence, what is an indicator and what is unverified. |
| Engineer / operator | Run pipelines, inspect stages, quarantine, audit trail and reports. |

### 2.4 Business value

- Moves discussion from anecdote to traceable evidence.
- Keeps customer complaints visible even when duplicated.
- Separates **evidence strength** from **business priority** and **verified risk**.
- Makes backlog coverage and gaps explicit.
- Provides reviewable factor names instead of opaque model labels.
- Creates an audit trail suitable for later production hardening.

---

## 3. What the System Does

### 3.1 Capability map

| Capability | Implementation |
| --- | --- |
| CSV feedback ingestion | `backend/app/services/ingestion.py` |
| PII redaction | `backend/app/intelligence/pii.py`, `text.py` |
| Language detection | `backend/app/intelligence/language.py` |
| Exact / near / repeat duplicate linking | `backend/app/intelligence/duplicates.py` |
| Data-quality checks | `backend/app/intelligence/quality.py` |
| Insight extraction | `backend/app/intelligence/extractor.py`, `providers.py` |
| Embeddings | `backend/app/intelligence/embeddings.py` |
| Canonical problem discovery | `backend/app/intelligence/clustering.py` |
| Taxonomy mapping | `backend/app/intelligence/taxonomy.py` |
| Measurement engine | `backend/app/intelligence/measurement.py` |
| Problem priority engine | `backend/app/intelligence/prioritization.py` |
| MDS theme map | `backend/app/intelligence/mds.py`, `services/mds.py` |
| FAMD problem dimensions | `backend/app/intelligence/problem_dimensions/**` |
| Factor prioritisation | `backend/app/intelligence/factor_prioritisation/**` |
| Factor narratives | `backend/app/intelligence/problem_dimensions/llm/**` |
| Portfolio narrative | `backend/app/intelligence/portfolio/**` |
| Evidence graph | `backend/app/services/mappings.py` |
| Backlog validation | `backend/app/services/backlog.py`, `intelligence/retrieval.py` |
| API | `backend/app/api/**`, `backend/app/main.py` |
| Persistence | `backend/app/repository.py`, `db.py`, `schema.py` |
| Frontend | `frontend/src/**` |
| Batch worker | `pipelines/jobs/run_pipeline.py` |
| Cloud scaffolding | `infra/terraform`, `workflows`, `sql`, `scripts`, `cloudbuild.yaml` |

### 3.2 Two main product flows

```text
Feedback flow:
raw feedback CSV
  -> validated/redacted feedback
  -> insights
  -> canonical customer problems
  -> taxonomy mappings
  -> measurements and priorities
  -> MDS theme map
  -> exploratory FAMD factors
  -> factor prioritisation
  -> factor narratives
  -> UI, API and audit records

Backlog flow:
backlog CSV
  -> normalised backlog items
  -> hybrid retrieval against prioritised factors or canonical problems
  -> relationship and coverage findings
  -> validation report
  -> product-owner review
  -> UI, CSV and JSON download
```

### 3.3 What it deliberately does not do

- It does not claim to measure real customer harm, revenue loss, churn or regulatory exposure.
- It does not infer technical root cause from customer language.
- It does not treat negative sentiment as a verified incident.
- It does not auto-approve or auto-reject a backlog.
- It does not let an LLM change FAMD statistics, priorities, MDS coordinates or canonical problems.
- It does not replace human ownership of organisational priority.

---

## 4. Key Concepts and Glossary

| Term | Meaning in this project |
| --- | --- |
| **Feedback record** | One validated, redacted customer comment with metadata such as source, platform and rating. |
| **Insight** | A structured interpretation of a clause or sentence: intent, aspect, symptom, sentiment, emotion, effort and whether it is a problem. |
| **Evidence link** | A persisted link between one feedback record and one canonical problem. |
| **Canonical problem** | A distinct, evidence-backed problem cluster discovered from similar insights. It has a title, statement, representative evidence and aggregates. |
| **Journey / taxonomy node** | A versioned banking-app module or feature such as Authentication, Login, UPI Payments or Card Limits. The taxonomy is a graph, not a single flat list. |
| **Mapping** | A link from a canonical problem to a primary taxonomy node, with confidence and review status. |
| **Measurement snapshot** | Windowed metrics for a problem, such as evidence volume, distinct customers, negative share, repeat complaints and source diversity. |
| **Priority snapshot** | A transparent weighted score with component scores, missing-metric metadata and escalation status. |
| **MDS theme map** | A two-dimensional projection where distance represents semantic similarity between problems. |
| **FAMD** | Factor Analysis of Mixed Data. It finds latent dimensions across mixed numeric and categorical problem features. |
| **Dimension / factor** | A latent FAMD axis. In this project, `D1`, `D2`, etc. are dimensions; `F1`, `F2`, etc. are factor identifiers used in prioritisation and narratives. |
| **Signed coefficient** | A problem's coordinate on a factor. Positive and negative values point in opposite directions; neither direction is inherently good or bad. |
| **Equation** | A readable representation of a problem as a weighted sum of factor coordinates: `CP_i = beta_i1*F1 + ... + beta_ik*Fk`. |
| **Factor prevalence** | Share of canonical problems meaningfully associated with a factor. |
| **Statistical importance** | Share of FAMD variation explained by a factor. |
| **Representation strength** | Share of problems whose row contribution meets the representation rule. |
| **Semantic coherence** | Deterministic concentration of journey, aspect, intent, symptom and banking-process attributes across the factor's represented problems. |
| **Backlog item** | A normalised unit of planned work with title, description, acceptance criteria and optional structured fields. |
| **Coverage / alignment** | Evidence-based assessment of whether a backlog item addresses a problem or factor. It is not an approval decision. |
| **Publication** | An immutable, appended record that makes a reviewed factor run the latest published version. |
| **Quarantine** | Rows rejected during ingestion, retained with reasons instead of being silently dropped. |
| **Idempotency key** | A client-supplied key that makes retrying a start request safe. |
| **Provenance** | The run, stage, version, configuration and evidence references that explain how an output was produced. |

---

## 5. System Architecture

### 5.1 High-level architecture

```text
Browser
  -> React + TypeScript frontend
  -> Nginx / Vite proxy
  -> FastAPI backend (the only service allowed to touch storage and analytics)
       -> Object store: local filesystem now, GCS adapter available
       -> Analytics store: SQLite now, BigQuery read adapter and migration DDL
       -> Intelligence layer: deterministic rules by default, optional LLM providers
       -> Feedback pipeline: validate_source -> ingest -> extract -> discover -> map
                            -> measurement -> priority -> MDS -> publish
       -> Dimension pipeline: features -> quality gates -> FAMD -> diagnostics
                            -> interpretation -> review -> publication
       -> Factor prioritisation -> narrative -> backlog validation -> reports
```

### 5.2 Runtime components

| Component | Responsibility |
| --- | --- |
| **Frontend** | React single-page application. Reads the API, renders analytical pages, starts allowed operations, downloads reports. |
| **FastAPI backend** | Validates requests, orchestrates services, enforces idempotency, records audit events and exposes read models. |
| **Repository** | The persistence gateway. Owns run IDs, stage tracking, queries, snapshots, review decisions and publications. |
| **Database** | SQLite by default at `data/local/bci.db`. Schema is created and migrated by `db.py`/`schema.py`. |
| **Object store** | Local immutable object store at `data/local/objects`; optional GCS adapter. |
| **Intelligence layer** | Rules, embeddings, clustering, taxonomy, measurement, priorities, FAMD, MDS, narratives. |
| **Batch worker** | CLI entry point for running feedback or dimension jobs outside the API process. |
| **Background threads** | Local API operations run pipelines in daemon threads so HTTP requests can return immediately. |

### 5.3 Design principles

1. **Deterministic core, optional intelligence.** Rules, formulas, thresholds and statistics are deterministic. LLMs are optional and constrained.
2. **Evidence traceability.** Outputs link back to problem IDs, feedback IDs, runs and versions.
3. **Missingness is meaningful.** A missing metric is not zero. Statuses such as `NO_DATA`, `UNKNOWN`, `PARTIAL` and `INSUFFICIENT_DATA` are preserved.
4. **No silent data loss.** Invalid rows are quarantined; duplicates are linked, not discarded.
5. **Human-in-the-loop.** Review gates protect factor names and publication. Backlog findings require product-owner interpretation.
6. **Separation of concerns.** Evidence strength, organisational priority, delivery cost, regulatory obligation and verified risk are distinct.
7. **Version everything important.** Code, schema, taxonomy, feature schema, methodology, prompts and models have versions.
8. **Append-only audit.** Reviews, publications and narratives are recorded rather than destructively overwritten.

---

## 6. Repository Map

```text
voice-analytics/
├── backend/
│   ├── app/
│   │   ├── main.py                 FastAPI app factory and service wiring
│   │   ├── config.py               Pydantic settings and defaults
│   │   ├── models.py               API request/response models
│   │   ├── db.py                   SQLite wrapper and column migrations
│   │   ├── schema.py               Full SQLite DDL
│   │   ├── repository.py           Persistence and read-model gateway
│   │   ├── storage.py              Local/GCS object store
│   │   ├── analytics/              SQLite and read-only BigQuery adapters
│   │   ├── api/                    HTTP routes
│   │   ├── services/               Orchestration services
│   │   └── intelligence/           Algorithms and analytical models
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   └── requirements-gcp.txt
├── frontend/
│   └── src/
│       ├── App.tsx                 Route table
│       ├── components/             Layout, charts, filters, UI primitives
│       ├── lib/                    API client, types, formatting, hooks
│       ├── pages/                  Analytical screens
│       └── styles.css
├── pipelines/jobs/run_pipeline.py  Batch worker CLI
├── taxonomy/banking_taxonomy_v1.yaml
├── sql/migrations/                 BigQuery DDL
├── sql/views/                      BigQuery views, where present
├── workflows/                      Cloud Workflows YAML
├── infra/terraform/                GCP infrastructure definitions
├── scripts/                        Dataset generation, deploy, SQL, teardown
├── tests/                          Pytest suite
├── docs/                           Detailed design and calculation documents
├── synthetic_banking_app_feedback_15000.csv
├── synthetic_banking_app_feedback_1800.csv
├── sample_backlog_upload.csv
├── cloudbuild.yaml
├── docker-compose.yml
├── docker/
├── Makefile
├── pyproject.toml
└── .env.example
```

### 6.1 Root files of note

| File | Purpose |
| --- | --- |
| `README.md` | Product overview, local run, API summary, provider modes and deployment notes. |
| `docs/pipeline-algorithms.md` | Stage-by-stage feedback and backlog algorithms. |
| `docs/algorithms-and-ui-calculations.md` | Traces UI values back to formulas and API fields. |
| `docs/problem_dimension_interpretation.md` | LLM factor naming, taxonomy context, provider fallback and persistence. |
| `docs/problem_portfolio.md` | Portfolio serialization, LangChain factor narrative agent and validation. |
| `docs/factor_analysis.md` | Canonical-problem factor coefficient method and caveats. |
| `docs/gcp-migration.md` | Current local-to-GCP gap and production blockers. |
| `prioritization.md` | Business framework for factor evidence prioritisation. |
| `document.md` | Broader customer-impact, risk, operational and financial measure catalogue. |
| `banking_customer_intelligence_gcp_build_prompt.md` | Original GCP target-architecture prompt. |

> **Workspace hygiene note:** the repository root also contains a stray 836 KB SQLite file named `None` and a 429 KB previous session log `session-ses_e73b.md`. Neither is imported by the application. They should not be treated as product source or committed as project documentation.

---

## 7. End-to-End Data Flows

### 7.1 Feedback flow

```text
Feedback CSV object
  -> validate_source
       object stat, SHA-256, size guard
  -> module_a_ingest
       CSV parse, header validation, row validation, normalization,
       PII redaction, language detection, duplicate linking,
       quarantine, data-quality checks
  -> module_b_extract
       sentence/clause segmentation, lexicon matching, multi-intent/aspect,
       sentiment, emotion, effort, outcome, confidence, evidence span guard
  -> module_c_discover
       embeddings, signature grouping, Union-Find merge,
       medoid representative, majority labels, evidence links
  -> module_d_map
       weighted lexical taxonomy matching plus embedding fallback,
       open-set proposal where needed
  -> measurement_engine
       lifetime, 90-day, current 30-day, previous 30-day metrics
  -> priority_engine
       customer impact, risk indicator, operational impact, trend, strategic fit
  -> mds_engine
       theme vectors, cosine distances, metric MDS, neighbours, stress
  -> module_e_publish
       daily aggregates, run summary and version stamps
  -> API read models and frontend
```

### 7.2 Backlog flow

```text
Backlog CSV
  -> upload
       parse, validate, store immutable object, quarantine invalid rows
  -> module_f_normalise
       profile intents/aspects/symptoms, resolve journey node, tokenize
  -> module_g_validate
       if a factor prioritisation run exists:
           hybrid retrieval against prioritised factors,
           factor coverage scoring and priority-weighted coverage
       otherwise:
           hybrid retrieval against canonical problems,
           node/intent/coverage alignment and rule-based relationship
  -> validation report
       findings, backlog ranking, relationship distribution,
       coverage matrix, gaps and limitations
  -> product-owner review
  -> API, UI, CSV/JSON download
```

### 7.3 Identifier conventions

| Prefix | Meaning |
| --- | --- |
| `RUN-YYYYMMDDHHMMSS-<hex6>` | Feedback pipeline run |
| `CORR-<hex12>` | Correlation ID |
| `FB-<hash>` | Deterministically derived feedback ID when needed |
| `CP-<hash>` | Canonical problem ID |
| `CL-<hash>` | Problem cluster ID |
| `DIM-YYYYMMDDHHMMSS-<hex6>` | FAMD dimension run |
| `DPUB-<hex16>` | Dimension publication |
| `FPR-YYYYMMDDHHMMSS-<hex6>` | Factor prioritisation run |
| `PPA-YYYYMMDDHHMMSS-<hex6>` | Problem portfolio analysis run |
| `SER-<hash>-<suffix>` | Portfolio serialization |
| `NAR-<hex16>` | Narrative |
| `VAL-<hex16>` | Narrative validation |
| `UP-<hex12>` | Backlog upload |
| `VRUN-<hex12>` | Backlog validation run |
| `RPT-<hex12>` | Validation report |

### 7.4 Version stamps

Important versions persist with runs and outputs:

| Version | Default / value |
| --- | --- |
| Code version | `0.1.0` |
| Schema version | `1.0.0` |
| Taxonomy version | `1.0.0` |
| Extraction provider | `rules-v1` by default |
| MDS methodology | `mds-1.0.0` |
| Problem priority methodology | `priority-1.0.0` |
| FAMD methodology | `famd-1.0.0` |
| Problem feature schema | `problem-dimensions-1.0.0` |
| Factor priority model | `factor-evidence-v1` |
| Factor equation version | `factor-equation-1.0.0` |
| Factor narrative agent | `factor-narrative-agent-1.1.0` |
| Portfolio serialization | `problem-portfolio-1.0.0` |

---

## 8. Feedback Pipeline: Modules A-E

### 8.1 Orchestration

The pipeline is started by `FeedbackPipelineService` in `backend/app/services/pipeline.py`. It records each stage in `pipeline_stages` and updates `pipeline_runs`.

Stages:

```text
validate_source
module_a_ingest
module_b_extract
module_c_discover
module_d_map
measurement_engine
priority_engine
mds_engine
module_e_publish
```

A run is versioned, stage-tracked and auditable. Quarantined rows remain visible with reasons.

### 8.2 Module A: ingestion, privacy and quality

Implemented mainly in:

- `backend/app/services/ingestion.py`
- `backend/app/intelligence/text.py`
- `backend/app/intelligence/pii.py`
- `backend/app/intelligence/language.py`
- `backend/app/intelligence/duplicates.py`
- `backend/app/intelligence/quality.py`

#### Input validation

- The input must be a CSV object from the object store.
- The object is size-checked against `max_feedback_bytes` (default 25 MB).
- The CSV is decoded as UTF-8 with BOM support.
- Delimiter detection uses `csv.Sniffer` with comma preference and an Excel fallback.
- Required columns must be present.
- Rows are capped by `pipeline_max_rows` (default 25,000).

Required feedback columns:

```text
feedback_id, submitted_at, source_type, source_channel, platform,
app_version, language, synthetic_customer_ref, rating_1_to_5,
feedback_title, feedback_text, is_synthetic
```

#### Row normalisation

- Unicode NFKC normalisation.
- Zero-width and non-breaking spaces removed.
- Whitespace collapsed.
- Timestamps parsed as ISO-8601; `Z` is converted to UTC; naive timestamps are treated as UTC.
- Ratings parsed as integers from 1 to 5.
- Short or missing feedback is quarantined.

#### PII redaction

PII is redacted **before persistence**. The default provider is regex. Optional Presidio and hybrid modes exist, with fallback to regex on failure.

Regex recognisers cover:

- email;
- card-like numbers;
- phone numbers;
- Aadhaar-like identifiers;
- account numbers;
- IFSC codes;
- UPI IDs;
- person-name patterns;
- URLs;
- residual long digit runs (9+ digits).

Redactions are replaced with labels such as `[EMAIL]`, and the label set is recorded in the ingestion manifest.

#### Language detection

Default is a script plus stopword heuristic. Optional `langdetect` and fastText providers exist. The synthetic dataset is primarily English with a minority of Hinglish samples.

#### Duplicate handling

Duplicates are **linked, never discarded**.

| Duplicate type | Method |
| --- | --- |
| Exact duplicate | SHA-256 fingerprint of normalised lowercase text. |
| Near duplicate | 3-token shingles, 64 MinHash permutations, 16-band LSH, exact Jaccard confirmation. Default threshold `0.85`, minimum 5 tokens. |
| Repeat complaint | Same synthetic customer reference plus lexical problem identity inside a configurable window, default 30 days. |

#### Data quality

Checks return explicit statuses rather than smoothing over bad data. Quality reports feed the UI and API.

### 8.3 Module B: insight extraction

Implemented in `backend/app/intelligence/extractor.py` and `providers.py`.

#### Segmentation

1. Split text into sentences using punctuation boundaries.
2. Find a global aspect/intent context.
3. Split into clauses using punctuation, contrast words and additive words.
4. Strip reporting prefixes such as “I think” or “the app says”.
5. Skip clauses with fewer than two tokens.

#### Lexicon matching

The deterministic lexicon (`lexicon.py`) contains:

- 38 intents;
- 44 aspects;
- 38 symptoms;
- sentiment keywords;
- emotion, effort and outcome regexes.

Matching uses earliest and longest entity wins.

#### Extraction output

For each useful clause, the extractor records:

- evidence span, guaranteed to be an exact substring;
- intent and aspect;
- symptom;
- sentiment: positive, negative, mixed or neutral;
- emotion;
- effort;
- outcome;
- whether the clause is a problem;
- confidence.

Confidence is a bounded linear signal-count formula, capped at `0.95`.

#### Sentiment and behavioural signals

- Sentiment uses weighted positive and negative keyword counts.
- Emotion, effort and outcome are ordered regex classifiers.
- Technical root cause is forced to `unknown`; customer text is not treated as a root-cause diagnosis.

#### Optional LLM extraction

Provider modes:

```text
EXTRACTION_PROVIDER=rules               deterministic, no API key
EXTRACTION_PROVIDER=gemini              Gemini
EXTRACTION_PROVIDER=openai_compatible   any OpenAI-compatible endpoint
```

The LLM path uses structured prompts, JSON parsing, exact-substring evidence guards and rule fallback. It does not replace the deterministic rules by default.

### 8.4 Module C: canonical problem discovery

Implemented in `backend/app/intelligence/embeddings.py` and `clustering.py`.

#### Embeddings

| Provider | Method |
| --- | --- |
| `local` (default) | TF-IDF (1-2 grams, sublinear TF, English stopwords) then TruncatedSVD/LSA, then L2 normalisation. Default 96 dimensions. |
| `sentence_transformer` | Sentence-transformers model. |
| `gemini` | Gemini embeddings, L2-normalised, batched. |
| `vertex` | Vertex AI embeddings. |

#### Discovery

1. Keep insights that are problems and have a reported problem.
2. Build embeddings for their text.
3. Group by a deterministic signature:
   - journey node + symptom key; or
   - journey node + `general` + intent.
4. Merge groups with Union-Find when:
   - they share the same non-`unmapped` journey node;
   - they share the same symptom key;
   - centroid cosine similarity is at least `min(0.9, threshold + 0.18)`.
   - With the default threshold `0.64`, this is effectively `0.82`.
5. Choose a medoid: the member with the highest mean cosine similarity to the group.
6. Use majority vote for aspect, symptom and intent.
7. Aggregate distinct customers, negative count, first/last seen and source counts.
8. Create canonical problems and evidence links.

Canonical problem IDs use `CP-` plus a truncated SHA-1 of the signature. Clusters use `CL-`.

### 8.5 Module D: taxonomy mapping

Implemented in `backend/app/intelligence/taxonomy.py` and used by `clustering.py`.

The taxonomy is a versioned graph in `taxonomy/banking_taxonomy_v1.yaml`. It contains module and feature nodes with display names, descriptions, synonyms, parent IDs and status. The bundled dataset covers all 62 active feature nodes.

Mapping is **rule-first, then semantic fallback, then open-set proposal**:

| Signal | Weight / threshold |
| --- | --- |
| Exact display-name phrase match | +3.0 |
| Exact synonym/alias phrase match | +2.2 |
| Shared token with display name/synonyms/aliases | +0.5 per token |
| Shared token with description | +0.25 per token |
| Module-node penalty | score × 0.92 |
| Acceptance threshold | 0.55 |
| Semantic fallback threshold | 0.45 |
| Open-set threshold | 0.35 |
| `best_node` acceptance | 1.4 default; 2.0 for backlog profiling |

Low-confidence mappings are stored as pending review. If no taxonomy node is a good fit, an open-set proposal is created with a suggested name and example evidence.

### 8.6 Module E: publication

Publication writes:

- daily aggregates into `analytics_problem_daily` using SQL `GROUP BY`;
- run summary metrics;
- model, taxonomy, schema and code versions.

The daily aggregate includes feedback counts and negative counts. A negative count is counted once per feedback/day when any linked insight for that feedback is negative or mixed.

---

## 9. Measurement and Problem Prioritisation

### 9.1 Measurement windows

Defaults:

```text
MEASUREMENT_WINDOW_DAYS = 90
TREND_BASELINE_DAYS = 30
TREND_CURRENT_DAYS = 30
```

`now` is the pipeline run time.

| Window | Bounds |
| --- | --- |
| Lifetime | All dated and undated linked evidence |
| Measurement | `now - 90 days` to `now` |
| Current trend | `now - 30 days` to `now` |
| Previous trend | The 30 days before the current trend window |

### 9.2 Windowed metrics

Each core metric is computed per window:

| Metric | Formula / meaning |
| --- | --- |
| `evidence_volume{window}` | Count of linked evidence in the window |
| `distinct_customers{window}` | Distinct non-null customer references |
| `negative_share{window}` | `(negative + mixed) / total` |
| `repeat_complaint_count{window}` | Sum of repeat-link counts for linked feedback |
| `source_diversity{window}` | Count of distinct source types |

Canonical names such as `evidence_volume`, `distinct_customers`, `negative_share`, `repeat_complaint_count` and `source_diversity` are aliases of the configured measurement window. Metadata records the alias.

Growth metrics:

```text
volume_growth_abs        = current_30d_volume - previous_30d_volume
volume_growth_pct        = (current - previous) / previous
customer_growth_abs      = current_30d_customers - previous_30d_customers
customer_growth_pct      = (current - previous) / previous
negative_share_change    = current_30d_negative_share - previous_30d_negative_share
assessment_velocity_delta = alias of volume_growth_abs
```

Percentage growth is `INSUFFICIENT_DATA` when the previous value is zero.

### 9.3 Coverage and status

Statuses distinguish observation from absence:

- `OK`: the window is covered and a value exists.
- `PARTIAL`: the dataset only partly overlaps the window.
- `NO_DATA`: the window is not covered; value is null, not zero.
- `INSUFFICIENT_DATA`: a denominator or required input is unavailable.

A covered window with no matching records returns `OK` with zero. An uncovered window returns `NO_DATA` with null. This is a central design choice: “we observed zero” must be distinguishable from “we have no coverage”.

### 9.4 Problem priority engine

Implemented in `backend/app/intelligence/prioritization.py`.

Weights:

```text
customer_impact        0.30
business_risk          0.30
operational_impact     0.15
trend                  0.15
strategic              0.10
```

They are normalised by their sum before scoring.

Component formulas:

```text
log_scale(value, cap) = clamp(log1p(value) / log1p(cap), 0, 1)

customer_impact =
    min(1,
        0.55 * log_scale(distinct_customers, 200)
      + 0.30 * negative_share
      + 0.15 * min(1, repeat_complaints / max(1, evidence_count)))

business_risk_indicator =
    min(1, sum(risk_term_weights_present) / 3 + 0.35 * negative_share)

operational_impact =
    min(1,
        0.60 * log_scale(evidence_count, 500)
      + 0.20 * log_scale(source_count, 5)
      + 0.20 * (1 if distinct_customers >= 3 else 0))

trend =
    clamp(0.5 + volume_growth_abs / 40, 0, 1)

strategic =
    module strategic weight, or 0.5 if no journey module
```

Risk terms and weights:

```text
unauthorized 1.0, fraud 1.0, money deducted 1.0, debited 0.9,
security 0.9, locked 0.7, blocked 0.7, kyc 0.7,
regulatory 0.8, duplicate payment 0.8,
payment failed 0.7, failed transfer 0.7
```

Each risk term contributes once if present in the concatenation of reported problems, symptoms and redacted feedback.

**Important:** the risk score is an **indicator score, not a verified incident score**. Every snapshot records:

```text
risk_indicators
risk_indicator_score
verified_risk.status = "NOT_VERIFIED"
verified_risk.verified_by = null
verified_risk.source = null
```

No verification is inferred from text.

Module strategic weights:

```text
payments 0.95, authentication 0.90, accounts 0.85, onboarding 0.85,
cards 0.80, loans 0.80, deposits 0.70, support 0.70,
notifications 0.60, navigation 0.55
```

Final score:

```text
priority_score =
      0.30 * customer_impact
    + 0.30 * business_risk
    + 0.15 * operational_impact
    + 0.15 * trend
    + 0.10 * strategic
```

Escalation:

- `ESCALATE` if `business_risk >= 0.75`.
- `ESCALATE` if `trend >= 0.8` and `customer_impact >= 0.5`.
- Otherwise `WATCH` if `priority_score >= 0.6`.
- Otherwise `NORMAL`.

Ranking is by priority score descending, then evidence count descending, then data completeness descending.

Missing inputs contribute zero to their component and are listed in `missing_metrics`. `data_completeness` records the fraction of components with usable input. A missing trend value is not silently replaced by a neutral 0.5.

---

## 10. MDS Theme Map

Implemented in `backend/app/intelligence/mds.py` and `backend/app/services/mds.py`.

### 10.1 Purpose

The theme map projects canonical customer problems into two dimensions so that semantically similar problems appear closer together. It is an orientation tool, not a severity or priority map.

### 10.2 Method

1. Build one representative vector per theme.
   - Prefer the centroid of member evidence vectors when all themes have member vectors with the same dimensionality.
   - Otherwise recompute theme vectors from theme text with one embedder so vector spaces are never mixed.
2. L2-normalise vectors.
3. Compute pairwise cosine distance: `1 - cosine similarity`, clipped to `[0, 2]`.
4. Symmetrise the distance matrix and set the diagonal to zero.
5. Run metric MDS on the precomputed distance matrix:
   - `n_components=2`
   - `random_state=42`
   - `normalized_stress="auto"`
   - `max_iter=300`
   - `n_init=4`
6. Compute nearest neighbours (default 5 per theme).
7. Persist points, display coordinates, vectors, neighbours and diagnostics.

### 10.3 Stress interpretation

| Normalised stress | Status |
| --- | --- |
| `<= 0.10` | `good` |
| `<= 0.20` | `caution` |
| `> 0.20` | `poor` |

### 10.4 Reading the map correctly

- Position means semantic similarity only.
- Bubble size represents evidence volume.
- Colour represents negative evidence share by default.
- Axes can rotate or reflect between runs. Compare similarity, not absolute coordinates.
- The service attaches priority and measurement data for business context, but MDS itself does not calculate either.

---

## 11. Problem Dimensions: The FAMD Layer

The problem-dimension layer is an **additive, exploratory layer** over canonical problems. It is not a replacement for the MDS theme map, the problem priority score or human judgement.

Implemented in:

```text
backend/app/services/problem_dimensions.py
backend/app/intelligence/problem_dimensions/
```

### 11.1 Why FAMD?

Customer problems have mixed data types: categorical features such as journey module or symptom, and numeric features such as evidence volume or negative share. FAMD finds latent axes that summarise relationships across those mixed features.

A useful intuition: FAMD tries to place problems in a smaller coordinate system so that problems with similar feature patterns sit near each other. The axes are mathematical constructs, not business concepts until an analyst interprets and names them.

### 11.2 Lifecycle

```text
QUEUED
  -> BUILDING_FEATURES
  -> VALIDATING_DATA
  -> FITTING_FAMD
  -> VALIDATING_RESULTS
  -> PENDING_REVIEW
  -> APPROVED
  -> PUBLISHED
```

Failures end in `FAILED`; rejected runs end in `REJECTED`.

### 11.3 Feature snapshot

The feature builder emits a versioned, window-aware feature row per canonical problem. Feature categories include:

- journey module, feature and stage;
- aspect;
- symptom category;
- customer intent;
- evidence volume;
- distinct customers;
- negative share;
- repeat rate;
- source diversity;
- high-effort share;
- task-failure share;
- negative-emotion share;
- volume growth;
- absolute volume growth;
- customer growth;
- negative-share change;
- assessment velocity;
- evidence confidence.

Feature roles are configurable:

- active;
- supplementary;
- excluded.

Forbidden inputs include IDs, titles, free text, raw feedback, MDS coordinates, `priority_score` and priority-derived fields. This prevents target leakage and keeps the factor model from simply rediscovering the priority score.

Missing measurement windows remain `None`, not zero. Attributes absent from the source data model are documented as unavailable rather than fabricated.

### 11.4 Data-quality gates

The layer checks:

- row count;
- duplicate IDs;
- forbidden fields;
- overall and per-column missingness;
- sparse categories;
- zero-variance numerics;
- duplicate numeric vectors;
- invalid rate denominators.

Critical failures block the run before model fitting. Warnings persist to the run.

Default minimum problems: `30`.

### 11.5 Preprocessing

- Missing numeric values are median-imputed **for fitting only**.
- Missing categorical values become an explicit `__MISSING__` level **for fitting only**.
- The imputation policy and fitted medians are recorded.
- Stored features retain their original missing values.
- Constant features are excluded from fitting and recorded.

### 11.6 FAMD fit

Configuration defaults:

```text
method: FAMD
library: prince
max_components: 20
publish_components: 12
min_problems: 30
min_category_count: 2
random_state: 42
bootstrap_iterations: 0
require_review: true
```

The implementation records:

- eigenvalues;
- explained variance;
- cumulative variance;
- total inertia;
- signed row coordinates;
- squared cosines;
- variable contributions;
- category contributions;
- problem-to-dimension memberships;
- diagnostics and warnings.

### 11.7 Coefficients and equations

For problem `i` and retained factors `1..k`:

```text
CP_i = beta_i1 * F1 + beta_i2 * F2 + ... + beta_ik * Fk
```

`beta` values are signed FAMD row coordinates. They describe the problem's position along each factor.

The relative squared-coordinate share is:

```text
relative_squared_coordinate_share_pct =
    s_ij^2 / sum_j(s_ij^2) * 100
```

It is null when every coordinate for the problem is zero.

**Interpretation guardrail:** these are descriptive associations. They are not regression coefficients, causal effects, percentage impacts, probabilities or severity scores. The versioned `COEFFICIENT_INTERPRETATION` string in `factor_equations.py` states this explicitly.

### 11.8 Diagnostics

- Optional bootstrap stability compares component alignment and flags unstable dimensions.
- Optional EFA uses scikit-learn `FactorAnalysis` on numeric features only.
- EFA is stored as a comparison, not as the publishing model.
- EFA is disabled by default.
- Quality checks, warnings, convergence and explained variance are persisted.

### 11.9 Analyst review

Each retained dimension receives a proposed name and description plus top variables and representative problems. Proposed labels are drafts.

An analyst can:

- approve;
- rename;
- request revision;
- reject.

No dimension is publishable until every retained dimension is approved.

### 11.10 Publication and rollback

Publishing requires an approved, non-rejected run. It writes immutable:

- definitions;
- contributions;
- scores;
- relative shares;
- equations;
- memberships;
- trends;
- publication metadata.

Latest-published reads resolve through the append-only `dimension_publications` table. Unpublished runs never replace the current publication. A previously published run can be republished to restore it as the latest publication; this appends a new publication record rather than mutating history.

Run-specific endpoints remain available for review and audit.

### 11.11 LLM factor naming

The optional LLM nomenclature pipeline:

1. Builds one complete factor-level equation payload per retained FAMD dimension.
2. Adds compact problem context and banking taxonomy context.
3. Asks a provider for structured factor names and descriptions.
4. Validates the response.
5. Persists proposals for analyst review.

There are **no deterministic factor-name fallbacks**. If no provider is available, factors remain unnamed rather than receiving invented business labels.

Provider modes: `gemini`, `openai_compatible`, `auto`. A fallback provider can be configured. Quota-limited Gemini can therefore be replaced or supplemented.

The LLM never changes canonical problems, priorities, MDS coordinates or FAMD statistics.

---

## 12. Factor Evidence Prioritisation

Factor prioritisation answers: **which retained factors have the strongest combined evidence and coherence?**

It is not a measure of customer harm, revenue impact or regulatory risk.

Implemented in:

```text
backend/app/services/factor_prioritisation.py
backend/app/intelligence/factor_prioritisation/
```

### 12.1 Inputs

The service reads only persisted FAMD outputs. It never refits FAMD and never changes problem scores, memberships or factor definitions.

Required inputs include:

- a structurally complete FAMD run with status `PENDING_REVIEW`, `APPROVED` or `PUBLISHED`;
- retained factor definitions;
- problem-factor scores;
- membership rows;
- row-contribution metadata;
- problem attributes;
- journey mappings;
- diagnostics with eigenvalues and total inertia;
- factor nomenclature, where available.

### 12.2 Weights

| Component | Weight |
| --- | ---: |
| Factor prevalence | 30% |
| Statistical importance | 25% |
| Problem representation strength | 25% |
| Semantic coherence | 20% |

Weights are normalised by their sum. The API can accept weight overrides, but unknown or negative weights are rejected.

### 12.3 Component formulas

**Prevalence**

```text
P_f = N_f / N * 100
```

- `N_f`: canonical problems in the validated membership set (`high_score` or `associated`).
- `N`: total canonical problems analysed.
- If persisted memberships are unavailable, the implementation can fall back to `|coordinate| >= membership_min_score` and marks the component provisional.

**Statistical importance**

```text
E_f = eigenvalue_f / total_inertia * 100
```

- If total inertia is unavailable, reported FAMD explained variance is used.
- If the eigenvalue is missing, the component is `UNKNOWN`.

**Representation strength**

```text
threshold = representation_multiplier * (100 / N)
R_f = represented_problems / N * 100
```

A problem is represented when its FAMD row contribution is at least the threshold. The default multiplier is `1.0`, so the threshold is the expected mean contribution.

If row contributions are unavailable, validated membership coverage is used and marked provisional.

**Semantic coherence**

Semantic coherence is a deterministic concentration measure, not an LLM judgement.

It computes five sub-scores:

1. journey coherence;
2. aspect coherence;
3. intent coherence;
4. symptom coherence;
5. banking-process coherence.

Each sub-score uses normalised Shannon entropy:

```text
concentration = 1 - (entropy / log(number_of_distinct_levels))
score = concentration * 100
```

The final semantic coherence is the mean of the assessable sub-scores. Missing sub-scores are `UNKNOWN`, not zero.

### 12.4 Final score

When all components are available:

```text
FS_f = 0.30 * P_f + 0.25 * E_f + 0.25 * R_f + 0.20 * C_f
```

For provisional scoring, available weights are renormalised:

```text
FS_f_provisional = sum(available w_k * S_fk) / sum(available w_k)
```

Missing components are never silently converted to zero.

### 12.5 Eligibility and score status

| Status | Meaning |
| --- | --- |
| `VALIDATED` | All components available and nomenclature approved. |
| `PROVISIONAL` | A score exists but some evidence or approval is incomplete. Provisional scoring may be allowed or disabled. |
| `INSUFFICIENT_EVIDENCE` | Not enough evidence for a defensible score. |
| `EXCLUDED` | Fails eligibility, for example insufficient problem count. |

The run also records:

- evidence coverage percentage;
- assessed components;
- missing components;
- nomenclature status;
- caveats;
- validation warnings;
- weighted contributions;
- component explanations;
- source tables and evidence references.

### 12.6 Ranking

Factors with a final score are ranked by:

1. score descending;
2. factor ID ascending.

The result is a deterministic, explainable evidence ranking. It is deliberately not called “business priority” or “risk”.

---

## 13. Factor Naming, Narrative Serialization and Portfolio Narrative

There are two related but distinct narrative mechanisms.

### 13.1 Factor narrative serialization (LangChain agent)

Implemented in:

```text
backend/app/intelligence/problem_dimensions/llm/narrative_agent.py
backend/app/intelligence/problem_dimensions/llm/equation_serializer.py
backend/app/intelligence/problem_dimensions/llm/taxonomy_context.py
backend/app/intelligence/problem_dimensions/llm/validation.py
```

Version: `factor-narrative-agent-1.1.0`.

Inputs:

- every canonical problem coefficient vector for one FAMD run;
- exact factor statistics;
- the repository banking taxonomy;
- problem titles, statements, journey/aspect/symptom context;
- top feature contributions.

Behaviour:

- one structured agent pass names and describes every retained factor;
- every claim must be grounded in supplied coefficient vectors, problem context and taxonomy;
- the agent must copy exact supplied statistics and must not recalculate them;
- technical identifiers such as `F1` or `D1` must not be used as factor names;
- no causal, revenue, churn or regulatory claims may be invented;
- ambiguous evidence must be stated and confidence lowered;
- approved analyst names are preserved;
- deterministic FAMD metrics are merged back after generation so the model cannot alter them;
- results are persisted.

The UI page is labelled **Narrative serialization** and operates on a selected factor-analysis run.

### 13.2 Portfolio narrative (Gemini provider)

Implemented in:

```text
backend/app/services/problem_portfolio.py
backend/app/intelligence/portfolio/
```

The portfolio flow:

1. Select a completed feedback run and an approved or published factor run.
2. Build a deterministic serialization with:
   - approved factor nomenclature;
   - factor profiles;
   - signed problem coefficients;
   - measurements;
   - priorities;
   - equations;
   - backlog coverage;
   - data-quality constraints;
   - an explicit list of unavailable attributes.
3. Canonicalise the serialization to JSON with sorted keys.
4. Compute a SHA-256 content hash.
5. Persist the serialization and hash.
6. Build a token-bounded narrative context:
   - full factor catalogue;
   - every problem in a compact index;
   - detailed evidence for the highest-priority problems.
7. Call Gemini through the official `google-genai` SDK with JSON Schema response mode.
8. Validate the narrative deterministically.
9. Persist narrative and validation result.
10. Retry with corrective instructions if validation fails.
11. Allow regeneration from the stored serialization without rerunning FAMD, measurements or prioritisation.

Deterministic validation rejects:

- technical IDs in prose;
- unapproved factor names;
- causal language around FAMD coefficients or coordinate shares;
- ungrounded references;
- unqualified provisional factors;
- missing-as-zero language.

Narratives and validation results are append-only.

### 13.3 What the narrative must not do

- It must not create new problems or metrics.
- It must not alter FAMD values.
- It must not convert missing data to zero.
- It must not claim verified regulatory, security, financial or churn risk unless the serialization explicitly contains a verified value.
- It must not present recommendations as guaranteed outcomes.

---

## 14. Evidence Mapping Graph

Implemented in `backend/app/services/mappings.py` and exposed at `GET /api/v1/mappings`.

The graph connects:

```text
feedback -> theme (canonical problem) -> factor -> backlog item
```

### 14.1 Nodes

| Node type | Source |
| --- | --- |
| Feedback | `feedback_records` for the selected or latest completed run |
| Theme | `customer_problems` |
| Factor | Latest factor prioritisation scores |
| Backlog | Backlog items from a matching factor-based validation report |

### 14.2 Links

| Link | Meaning |
| --- | --- |
| `feedback_theme` | Evidence link between feedback and canonical problem, with weight and evidence count |
| `theme_factor` | Problem membership in a factor, with score, margin, membership type and ambiguity flag |
| `factor_backlog` | Backlog finding for a factor, with relationship, coverage, alignment score and support count |

### 14.3 Readiness states

- `NO_FEEDBACK_RUN`: no completed feedback run.
- `NO_THEMES`: the feedback run has no canonical themes.
- `READY`: graph is fully available.
- `PARTIAL`: some layer is missing, with warnings.

The graph is read-only. It exists to make end-to-end traceability inspectable.

---

## 15. Backlog Validation: Modules F-G

Implemented in:

```text
backend/app/services/backlog.py
backend/app/intelligence/retrieval.py
```

### 15.1 Upload and normalisation

Required columns:

```text
backlog_id, title, description
```

Optional richer columns include:

- acceptance criteria;
- product area;
- priority;
- business goal;
- intended outcome;
- customer intent;
- target feature;
- target journey;
- functional scope;
- organisational objective;
- source system.

Rules:

- maximum 1,000 rows;
- duplicate backlog IDs are row errors;
- missing title or description is a row error;
- cells beginning with `=`, `+`, `-`, `@`, tab or carriage return trigger a formula-injection warning and are neutralised on export;
- acceptance criteria are split on `|` and newlines, then on `;`;
- upload status is `validated` if there are no row errors, otherwise `validated_with_errors`.

The raw file is stored in the object store with an immutable generation, SHA-256 and size.

### 15.2 Profiling

Backlog text is built from title, description, acceptance criteria, product area and optional structured fields.

- Intent, aspect and symptom keys come from the same regex lexicon as the feedback pipeline.
- Journey node resolution order:
  1. `product_area` alias map;
  2. first aspect whose `node_id` exists in the taxonomy;
  3. `best_node(text, threshold=2.0)`.
- Tokens are retained for Jaccard similarity.

### 15.3 Validation basis

The service checks for the latest factor prioritisation run.

- If a factor run exists with scores, validation uses the **factor prioritisation basis**.
- Otherwise it falls back to **canonical problem validation**.

This means reports can have two bases:

```text
validation_basis = "factor_prioritisation"
validation_basis = "canonical_problems"
```

### 15.4 Hybrid retrieval

`HybridRetriever` fits on the target texts:

- canonical problem `title + statement`; or
- factor narrative text and supporting problems.

For each backlog item:

- dense score = cosine similarity between backlog embedding and target embeddings;
- sparse score = cosine similarity between backlog TF-IDF vector and target TF-IDF matrix;
- dense and sparse matrices are row-normalised by their row maximum;
- combined score:

```text
combined = 0.6 * dense_normalized + 0.4 * sparse_normalized
```

If a cross-encoder reranker is configured and installed, the top 8 candidates are blended as:

```text
0.6 * cross_encoder_score + 0.4 * hybrid_score
```

Retrieval only selects candidates. It is not the final decision.

### 15.5 Canonical-problem alignment

For each candidate problem:

- `similarity` = hybrid retrieval score;
- `lexical` = Jaccard overlap between backlog and problem tokens;
- `node_alignment`:
  - `1.0` exact node;
  - `0.6` same taxonomy module;
  - `0.0` otherwise;
- `intent_alignment`:
  - `1.0` problem intent in backlog intents;
  - `0.8` problem aspect matches a backlog aspect;
  - `0.7` backlog intent's node hint equals the problem aspect node;
  - `0.0` otherwise;
- `coverage` = covered problem symptoms / detected problem symptoms.

Alignment score:

```text
alignment_score =
      0.35 * max(similarity, lexical)
    + 0.25 * node_alignment
    + 0.20 * intent_alignment
    + 0.20 * coverage
```

Relationship decision tree:

```text
signal = max(similarity, lexical)

if node_alignment == 0 and signal < 0.22:
    if signal < 0.12: CONTRADICTS_OR_OUT_OF_SCOPE
    else:             NO_CLEAR_RELATIONSHIP

else if node_alignment >= 0.6 and coverage >= 0.5
        and intent_alignment >= 0.45 and signal >= 0.18:
    if score >= 0.5:  ADDRESSES
    else:             NEEDS_REVIEW

else if node_alignment >= 0.6 and (coverage > 0 or signal >= 0.22):
    PARTIALLY_ADDRESSES

else if node_alignment >= 0.6:
    RELATED_BUT_NOT_SOLVING

else if signal >= 0.3:
    RELATED_BUT_NOT_SOLVING

else if signal >= 0.18:
    NEEDS_REVIEW

else:
    NO_CLEAR_RELATIONSHIP
```

Post-processing:

- `ADDRESSES` or `PARTIALLY_ADDRESSES` with fewer than 2 supporting feedback mentions becomes `NEEDS_REVIEW`.
- `ADDRESSES` with coverage between `0.25` and `0.45` becomes `NEEDS_REVIEW`.
- A candidate is dropped when it is `NO_CLEAR_RELATIONSHIP` and both similarity `< 0.18` and node alignment is zero.

Overall alignment:

| Verdict | Condition |
| --- | --- |
| `strong` | Best `ADDRESSES` has score >= 0.55 and at least 2 supporting mentions |
| `needs_review` | Any weaker `ADDRESSES` or any `NEEDS_REVIEW` |
| `partial` | Any `PARTIALLY_ADDRESSES` |
| `weak` | Only `RELATED_BUT_NOT_SOLVING` or lower |
| `unsupported` | No findings or only no-relationship |

### 15.6 Factor-based alignment

When prioritisation exists, the report compares backlog items to prioritised factors.

For each backlog/factor pair:

```text
semantic = dense embedding similarity
sparse   = sparse TF-IDF similarity
lexical  = token Jaccard
coverage = 0.5 * semantic + 0.3 * sparse + 0.2 * lexical
priority_weighted_coverage = coverage * factor_priority_score
```

Factor relationship:

| Condition | Relationship |
| --- | --- |
| `coverage >= 0.45` and (`semantic >= 0.30` or `lexical >= 0.25`) | `COVERS` |
| `coverage >= 0.30` | `PARTIALLY_COVERS` |
| `coverage >= 0.20` | `RELATED` |
| `coverage >= 0.12` | `NEEDS_REVIEW` |
| otherwise | `NOT_COVERED` |

Backlog items are ranked by:

1. priority alignment score;
2. best coverage;
3. backlog ID.

`priority_alignment_pct` is the covered priority mass divided by total factor priority mass.

Overall alignment:

- `strong` when a `COVERS` exists, priority alignment is at least `0.25`, and the best factor rank is at most `6`;
- otherwise `partial` when a `COVERS` exists or any partial coverage exists;
- `weak` when only related or review findings exist;
- `unsupported` otherwise.

### 15.7 Coverage matrix and gaps

Per backlog item:

```text
ac_coverage = mean(finding.ac_coverage for all findings)
```

In canonical-problem mode, this is average symptom coverage, not a literal percentage of acceptance criteria satisfied. In factor mode it is average factor coverage.

High-evidence uncovered problems (canonical mode):

- not addressed by any `ADDRESSES` or `PARTIALLY_ADDRESSES`;
- evidence count >= 5;
- sorted by problem query order;
- capped at 12.

High-priority uncovered factors (factor mode):

- factor priority rank <= 5;
- no backlog item covers or partially covers it.

The report records limitations explicitly:

- alignment derives only from supplied feedback and backlog text;
- organisational priority is not calculated;
- `NEEDS_REVIEW` must be resolved by a product owner;
- similarity retrieves candidates but never makes the final decision.

### 15.8 Review and download

Product-owner review is recorded against the report. The report can be downloaded as CSV or JSON. CSV cells are protected against spreadsheet formula injection.

---

## 16. API Reference

Base path: `/api/v1`  
Interactive docs: `/docs`  
Health: `/api/v1/health`

### 16.1 Conventions

- Start endpoints accept an optional `Idempotency-Key`.
- Pipeline starts return `202 Accepted` with a run ID.
- Review endpoints record reviewer, decision and note in the audit trail.
- Errors are returned as HTTP problem details with `detail`.
- Large reports can be downloaded as CSV or JSON.

### 16.2 Main endpoints

#### Health and metadata

```text
GET  /health
GET  /meta/source
GET  /admin/overview
```

#### Feedback sources and runs

```text
GET  /feedback-sources
POST /feedback-sources
POST /feedback-pipelines
GET  /feedback-pipelines
GET  /feedback-pipelines/{run_id}
```

#### Feedback analytics

```text
GET  /feedback/summary
GET  /feedback/options
GET  /problems
GET  /problems/{problem_id}
GET  /problems/{problem_id}/measurement
GET  /problems/{problem_id}/priority
GET  /priorities
```

#### Quality, duplicates and relationships

```text
GET  /data-quality
GET  /duplicates
GET  /diagnostics
GET  /problem-relationships
```

#### Taxonomy and journey

```text
GET  /taxonomy
GET  /taxonomy/proposals
POST /taxonomy/proposals/{proposal_id}/review
GET  /journey
```

#### MDS theme map

```text
GET  /problem-map
POST /problem-map/recompute
GET  /problem-map/{problem_id}
```

#### Problem dimensions / FAMD

```text
GET  /problem-dimensions/status
POST /problem-dimensions/runs
GET  /problem-dimensions/runs
GET  /problem-dimensions/runs/{run_id}
GET  /problem-dimensions/runs/{run_id}/dimensions/{dimension_id}
GET  /problem-dimensions/runs/{run_id}/problems/{problem_id}
GET  /problem-dimensions/runs/{run_id}/problems/{problem_id}/profile
GET  /problem-dimensions/runs/{run_id}/coefficients
GET  /problem-dimensions/runs/{run_id}/coefficients.csv
GET  /problem-dimensions/runs/{run_id}/variables
GET  /problem-dimensions/runs/{run_id}/interpretation
GET  /problem-dimensions/runs/{run_id}/dimensions/{dimension_id}/interpretation
POST /problem-dimensions/runs/{run_id}/interpretation/regenerate
POST /problem-dimensions/runs/{run_id}/problems/{problem_id}/name-factors
GET  /problem-dimensions/runs/{run_id}/narrative-serialization
POST /problem-dimensions/runs/{run_id}/narrative-serialization
GET  /problem-dimensions/latest
GET  /problem-dimensions/latest/dimensions/{dimension_id}
GET  /problem-dimensions/latest/problems/{problem_id}
POST /problem-dimensions/runs/{run_id}/dimensions/{dimension_id}/review
POST /problem-dimensions/runs/{run_id}/publish
```

#### Factor analysis alias

```text
GET  /factor-analysis/status
POST /factor-analysis/runs
GET  /factor-analysis/runs
GET  /factor-analysis/runs/{run_id}
GET  /factor-analysis/runs/{run_id}/coefficients
GET  /factor-analysis/runs/{run_id}/variables
GET  /factor-analysis/runs/{run_id}/problems/{problem_id}
```

#### Factor prioritisation

```text
GET  /factor-prioritisation/status
POST /factor-prioritisation/runs
GET  /factor-prioritisation/runs
GET  /factor-prioritisation/runs/latest
GET  /factor-prioritisation/runs/{run_id}
GET  /factor-prioritisation/runs/{run_id}/scores
GET  /factor-prioritisation/runs/{run_id}/factors/{factor_id}
POST /factor-prioritisation/runs/{run_id}/factors/{factor_id}/semantic-assessment/review
```

#### Problem portfolio narrative

```text
GET  /problem-portfolio/status
POST /problem-portfolio/runs
GET  /problem-portfolio/runs
GET  /problem-portfolio/runs/{run_id}
GET  /problem-portfolio/runs/{run_id}/serialization
GET  /problem-portfolio/runs/{run_id}/narrative
POST /problem-portfolio/runs/{run_id}/narrative/regenerate
GET  /problem-portfolio/runs/{run_id}/validation
GET  /problem-portfolio/latest
GET  /problem-portfolio/latest/narrative
```

#### Evidence graph

```text
GET  /mappings
```

#### Backlog validation

```text
GET  /backlog-template
POST /backlog-uploads
POST /backlog-uploads/sample
GET  /backlog-uploads
GET  /backlog-uploads/{upload_id}
POST /backlog-uploads/{upload_id}/validate
GET  /backlog-validation-runs/{run_id}
GET  /backlog-validation-reports
GET  /backlog-validation-reports/{report_id}
GET  /backlog-validation-reports/{report_id}/coverage
GET  /backlog-validation-reports/{report_id}/download?format=csv|json
POST /backlog-validation-reports/{report_id}/review
```

#### Reviews

```text
POST /problems/{problem_id}/review
POST /taxonomy/proposals/{proposal_id}/review
POST /backlog-validation-reports/{report_id}/review
```

---

## 17. Frontend Application

### 17.1 Stack

| Area | Choice |
| --- | --- |
| Framework | React 18.3.1 |
| Language | TypeScript 5.7.2 |
| Build | Vite 6.0.7 |
| Routing | react-router-dom 6.28.1 |
| Charts | Recharts 2.15.0 |
| Icons | lucide-react 0.468.0 |
| API base | `/api/v1` |
| Dev port | `5173` |
| Preview port | `4173` |
| API proxy | `/api` -> `http://localhost:8000` |

### 17.2 Actual route table

From `frontend/src/App.tsx`:

| Route | Page | Purpose |
| --- | --- | --- |
| `/` | `JourneyPage` | Taxonomy tree with evidence volume; entry point. |
| `/journey` | `JourneyPage` | Same taxonomy explorer via explicit path. |
| `/problems` | `ProblemsPage` | Search and filter canonical customer problems. |
| `/problems/:problemId` | `ProblemDetailPage` | Evidence, measurement, priority and dimension membership. |
| `/themes` | `ThemeMapPage` | MDS semantic theme map. |
| `/mappings` | `MappingsPage` | Directed feedback -> theme -> factor -> backlog graph. |
| `/dimensions` | `DimensionsPage` | FAMD runs, review and publish. |
| `/dimensions/:dimensionId` | `DimensionDetailPage` | Variable contributions, category levels, trends and review provenance. |
| `/portfolio` | `PortfolioPage` | All-problem coefficient matrix and factor narrative serialization. |
| `/prioritization` | `PrioritizationPage` | Deterministic factor evidence prioritisation. |
| `/backlog` | `BacklogPage` | Select/upload backlog and start validation. |
| `/reports/:reportId` | `ReportPage` | Backlog/factor coverage report, review and download. |

`OverviewPage.tsx` and `RunsPage.tsx` exist in the repository but are **not routed or displayed** in the current `App.tsx`. Some repository documentation still lists an older, smaller route set. The table above reflects the current code.

### 17.3 Navigation

The sidebar exposes:

```text
Journey explorer
Customer problems
Theme map
Mappings
Factor analysis
Prioritization
Narrative serialization
Backlog validation
```

The top bar shows:

- environment status;
- code version;
- whether a completed run is available;
- a persistent synthetic-data warning.

The sidebar also shows provider, taxonomy version, schema version and storage mode from `/meta/source`.

### 17.4 Page details

#### Journey explorer

- Renders the taxonomy tree.
- Shows evidence volume at each node.
- Allows drill-down from journey/module/feature into associated problems.
- Uses `/journey`.

#### Customer problems

- Uses `/feedback/options` for filters.
- Searches `/problems` with pagination.
- Supports journey, status and search filters.
- Displays problem title, journey, evidence count, customer count, negative count and validation status.
- Clicking a row opens problem detail.

#### Problem detail

Uses:

```text
/problems/{id}
/problems/{id}/measurement
/problems/{id}/priority
/problem-dimensions/latest/problems/{id}
```

Shows:

- title, statement and journey;
- evidence and customer counts;
- impact measurement with statuses;
- priority score, component scores and escalation;
- risk-indicator caveat;
- evidence details;
- taxonomy mapping and review state;
- published dimension membership.

Measurement values display statuses distinctly. A missing value is shown as unknown or no data, not as zero.

#### Theme map

- Uses `/problem-map`.
- Displays MDS stress, uncovered themes, escalations and semantic space.
- Bubble size = evidence volume; colour = negative evidence share by default.
- Selecting a bubble shows problem detail, measurement and priority.
- A rebuild button calls `/problem-map/recompute`.

#### Mappings

- Uses `/mappings`.
- Renders a directed graph of feedback, themes, factors and backlog items.
- Supports search and path inspection.
- Handles `NO_FEEDBACK_RUN`, `NO_THEMES`, `READY` and `PARTIAL` states.

#### Factor analysis

- Uses `/problem-dimensions/status`, `/feedback-pipelines` and `/problem-dimensions/runs`.
- Starts FAMD runs.
- Lists retained dimensions and review states.
- Supports approve, rename, request revision and reject.
- Publishes only when all dimensions are approved.
- Starts narrative serialization for a run.

#### Dimension detail

- Uses run-specific or latest-published endpoints.
- Shows:
  - analyst name and description;
  - variable contributions;
  - influential category levels;
  - descriptive trends;
  - review provenance;
  - top problems ordered by absolute coordinate;
  - evidence and provenance.
- Clearly labels trends as descriptive, not forecasts.

#### Prioritization

- Uses `/factor-prioritisation/status`, `/runs`, `/runs/{id}`.
- Starts prioritisation runs with configurable weights.
- Displays ranked factors with 0-100 priority bars.
- Shows component scores, evidence coverage, statuses and caveats.
- Allows semantic-assessment review notes.

#### Narrative serialization

- Uses `/problem-dimensions/status` and factor-run endpoints.
- Shows all canonical problems and factor coefficients for a selected run.
- Starts the LangChain factor narrative agent.
- Displays factor names, descriptions and narrative status.
- Preserves approved names.

#### Backlog validation

- Lists backlog uploads.
- Shows upload detail and row validation status.
- Starts validation against the latest prioritised factors where available.
- Navigates to the generated report.

#### Validation report

- Uses `/backlog-validation-reports/{id}`.
- Renders summary stats, relationship distribution, backlog ranking, item findings, coverage matrix and uncovered gaps.
- Supports product-owner review.
- Supports CSV and JSON download.
- Handles both factor-based and canonical-problem-based reports.

### 17.5 UI calculation caveats

The frontend displays values from the API rather than recomputing statistics. Important caveats are surfaced in labels or helper text:

- priority is evidence prioritisation, not verified business risk;
- risk indicators are not verified incidents;
- MDS position is semantic, not severity;
- FAMD coefficients are associations;
- “AC coverage” is average symptom/factor coverage, not a literal percentage of acceptance criteria;
- missing values are status-bearing, not zero.

---

## 18. Data Model and Persistence

### 18.1 Storage modes

| Store | Default | Production target |
| --- | --- | --- |
| Analytics database | SQLite at `data/local/bci.db` | BigQuery |
| Object store | Local filesystem at `data/local/objects` | GCS with versioning |
| Shared state | SQLite | BigQuery and external orchestration |

SQLite is the write store. The BigQuery adapter is currently read-only.

### 18.2 Schema management

- `backend/app/schema.py` contains the SQLite DDL.
- `backend/app/db.py` contains:
  - connection handling;
  - JSON serialisation helpers;
  - guarded `COLUMN_MIGRATIONS` that add backward-compatible columns.
- Migrations are additive and guarded so existing local databases continue to work.

### 18.3 Main table groups

#### Operations and audit

```text
pipeline_runs
pipeline_stages
ingestion_manifests
audit_log
review_decisions
human_review_decisions
model_execution_history
data_quality_reports
app_meta
scoring_methodology_versions
```

#### Feedback and insights

```text
feedback_records
feedback_quarantine
feedback_duplicate_candidates
extracted_insights
```

#### Canonical problems and evidence

```text
customer_problems
problem_evidence
problem_clusters
problem_relationships
problem_symptoms
problem_journey_mappings
```

#### Taxonomy

```text
taxonomy_nodes
problem_mappings
taxonomy_proposals
```

#### Measurement and priority

```text
analytics_problem_daily
problem_metrics_daily
problem_measurement_snapshots
problem_priority_snapshots
```

#### MDS

```text
problem_theme_vectors
problem_mds_runs
problem_mds_points
problem_mds_neighbors
```

#### Problem dimensions

```text
problem_feature_snapshots
dimension_analysis_runs
problem_dimension_scores
problem_dimension_equations
dimension_definitions
dimension_problem_interpretations
dimension_evidence_aggregations
dimension_narrative_serializations
dimension_nomenclature_proposals
dimension_llm_processing
dimension_variable_contributions
dimension_problem_membership
dimension_trends
dimension_publications
```

#### Factor prioritisation

```text
factor_prioritisation_runs
factor_prioritisation_scores
factor_prioritisation_evidence
factor_semantic_assessments
```

#### Portfolio narrative

```text
problem_portfolio_analysis_runs
problem_factor_nomenclature
problem_factor_profiles
problem_portfolio_serializations
problem_portfolio_narratives
problem_narrative_validation
```

#### Backlog and validation

```text
backlog_uploads
backlog_items
validation_runs
validation_reports
validation_findings
backlog_problem_candidates
backlog_coverage_matrix
report_reviews
```

#### Guarded advanced analytics

```text
survival_analysis_results
conjoint_analysis_results
```

These tables exist for future guarded analyses. Survival and conjoint are disabled and refuse to run without the required experimental or event inputs.

### 18.4 Object storage

The object store provides:

- immutable object generations;
- SHA-256 and size metadata;
- local filesystem implementation;
- GCS adapter configured via `OBJECT_STORE=gcs`, `GCS_BUCKET` and prefixes.

Local layout:

```text
data/local/
├── bci.db
└── objects/
```

### 18.5 BigQuery migration assets

SQL migrations:

```text
001_bigquery_schema.sql
002_bigquery_schema_enhancements.sql
003_bigquery_mds.sql
004_bigquery_problem_dimensions.sql
005_bigquery_problem_dimension_coefficients.sql
006_bigquery_problem_portfolio.sql
007_bigquery_factor_prioritisation.sql
```

Datasets:

```text
ops, staging, curated, intelligence, taxonomy, backlog, validation
```

---

## 19. Configuration

Configuration is defined in `backend/app/config.py` using Pydantic settings. `.env.example` is the authoritative list of supported settings. Settings are read from `.env` or the environment.

### 19.1 Important settings

| Setting | Default | Purpose |
| --- | --- | --- |
| `ENVIRONMENT` | `local` | Runtime environment label. |
| `API_PREFIX` | `/api/v1` | API base path. |
| `DATA_DIR` | `data` | Root for local database and objects. |
| `DATABASE_PATH` | unset | Optional explicit SQLite path. |
| `OBJECT_STORE` | `local` | `local` or `gcs`. |
| `GCS_BUCKET` | empty | GCS bucket for objects. |
| `AUTO_SEED_SOURCE` | `true` | Seed the sample feedback source on first start. |
| `AUTO_RUN_SAMPLE` | `true` | Automatically start a sample feedback pipeline. |
| `PIPELINE_MAX_ROWS` | `25000` | Feedback row cap. |
| `MAX_FEEDBACK_BYTES` | `25 MB` | Feedback object size cap. |
| `MAX_BACKLOG_BYTES` | `10 MB` | Backlog object size cap. |
| `EXTRACTION_PROVIDER` | `rules` | `rules`, `gemini`, `openai_compatible`. |
| `LLM_MODEL` | `gemini-2.0-flash` | Generic LLM model. |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Gemini model setting. |
| `EMBEDDING_PROVIDER` | `local` | `local`, `sentence_transformer`, `gemini`, `vertex`. |
| `EMBEDDING_DIMENSIONS` | `96` | Local embedding dimensions. |
| `CLUSTERING_SIMILARITY_THRESHOLD` | `0.64` | Base clustering threshold. |
| `NEAR_DUPLICATE_THRESHOLD` | `0.85` | Near-duplicate Jaccard threshold. |
| `REPEAT_COMPLAINT_WINDOW_DAYS` | `30` | Repeat complaint window. |
| `PII_PROVIDER` | `regex` | `regex`, `presidio`, `hybrid`. |
| `LANGUAGE_DETECTION_PROVIDER` | `heuristic` | `heuristic`, `langdetect`, `fasttext`. |
| `TAXONOMY_ACCEPT_THRESHOLD` | `0.55` | Mapping acceptance. |
| `TAXONOMY_SEMANTIC_THRESHOLD` | `0.45` | Semantic fallback. |
| `TAXONOMY_OPEN_SET_THRESHOLD` | `0.35` | Open-set proposal. |
| `MEASUREMENT_WINDOW_DAYS` | `90` | Main measurement window. |
| `TREND_CURRENT_DAYS` | `30` | Current trend window. |
| `TREND_BASELINE_DAYS` | `30` | Previous trend window. |
| `ENABLE_MDS` | `true` | Enable theme map. |
| `MDS_MAX_THEMES` | `500` | Theme map cap. |
| `ENABLE_PROBLEM_DIMENSIONS` | `true` | Enable FAMD layer. |
| `PROBLEM_DIMENSION_MIN_PROBLEMS` | `30` | Minimum problems for FAMD. |
| `PROBLEM_DIMENSION_MAX_COMPONENTS` | `20` | Maximum fitted components. |
| `PROBLEM_DIMENSION_PUBLISH_COMPONENTS` | `12` | Retained/published components. |
| `PROBLEM_DIMENSION_REQUIRE_REVIEW` | `true` | Require analyst approval. |
| `ENABLE_PROBLEM_DIMENSION_EFA` | `false` | Optional EFA comparison. |
| `PROBLEM_DIMENSION_LLM_ENABLED` | `true` | Enable factor naming. |
| `PROBLEM_DIMENSION_LLM_PROVIDER` | `gemini` | `gemini`, `openai_compatible`, `auto`. |
| `ENABLE_FACTOR_PRIORITISATION` | `true` | Enable factor ranking. |
| `FACTOR_PRIORITISATION_WEIGHT_PREVALENCE` | `0.30` | Prevalence weight. |
| `FACTOR_PRIORITISATION_WEIGHT_STATISTICAL` | `0.25` | Statistical weight. |
| `FACTOR_PRIORITISATION_WEIGHT_REPRESENTATION` | `0.25` | Representation weight. |
| `FACTOR_PRIORITISATION_WEIGHT_SEMANTIC` | `0.20` | Semantic weight. |
| `ENABLE_PROBLEM_PORTFOLIO` | `true` | Enable portfolio narrative. |
| `PORTFOLIO_NARRATIVE_PROVIDER` | `gemini` | Portfolio narrative provider. |
| `ANALYTICS_BACKEND` | `sqlite` | `sqlite` or `bigquery` read adapter. |
| `CORS_ORIGINS` | localhost ports | Allowed browser origins. |
| `REVIEW_ROLES` | admin, journey_expert, product_owner, analyst | Intended review roles. |
| `SYNTHETIC_WARNING` | `true` | Keep synthetic warning. |

### 19.2 Provider modes

Extraction:

```text
rules               deterministic, no key
gemini              GEMINI_API_KEY
openai_compatible   OPENAI_BASE_URL, OPENAI_MODEL, optional OPENAI_API_KEY
```

Embeddings:

```text
local               TF-IDF + SVD
sentence_transformer
gemini
vertex
```

PII:

```text
regex
presidio
hybrid
```

Language:

```text
heuristic
langdetect
fasttext
```

Analytics:

```text
sqlite
bigquery            read-only adapter
```

---

## 20. Running the Project

### 20.1 Prerequisites

- Python 3.11+ (3.13 tested)
- Node.js 20+ and npm
- Docker 24+ with Compose v2, optional

### 20.2 Local setup

```bash
cp .env.example .env
make install
make test
```

Start the backend:

```bash
make dev-backend
```

Backend: `http://127.0.0.1:8000`  
API docs: `http://127.0.0.1:8000/docs`

Start the frontend in another terminal:

```bash
make dev-frontend
```

Frontend: `http://127.0.0.1:5173`

On first backend start:

- the sample feedback source is seeded;
- a feedback pipeline starts automatically.

Disable with:

```bash
AUTO_SEED_SOURCE=false
AUTO_RUN_SAMPLE=false
```

### 20.3 Direct commands

Backend:

```bash
source .venv/bin/activate
PYTHONPATH=backend python -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

Frontend:

```bash
cd frontend
npm ci
npm run dev -- --host 127.0.0.1 --port 5173
```

Feedback batch worker:

```bash
PYTHONPATH=backend python -m pipelines.jobs.run_pipeline --force
```

Dimension batch worker:

```bash
PYTHONPATH=backend python -m pipelines.jobs.run_pipeline --mode dimensions --feedback-run-id RUN-...
```

### 20.4 Docker Compose

```bash
cp .env.example .env
make docker-up
```

Ports:

- frontend: `http://localhost:8080`
- backend: `http://localhost:8000`

Stop and remove data volume:

```bash
make docker-down
```

### 20.5 Typical first-use workflow

1. Wait for the automatic feedback pipeline to finish.
2. Open **Journey explorer** and **Customer problems** to inspect evidence.
3. Open a problem detail page to inspect measurement and priority.
4. Open **Theme map** to see semantic clusters.
5. Open **Factor analysis** and start a FAMD run.
6. Review and approve every factor name.
7. Publish the factor run.
8. Open **Prioritization** and run factor evidence prioritisation.
9. Open **Narrative serialization** to generate factor narratives.
10. Open **Backlog validation**, upload `sample_backlog_upload.csv` or use the sample, and validate.
11. Open the report, review findings and download CSV/JSON.
12. Open **Mappings** to trace feedback -> theme -> factor -> backlog.

---

## 21. Testing and Quality Gates

### 21.1 Test suite

- Framework: pytest.
- Configuration: `pyproject.toml`.
- Test path: `tests`.
- Python path: `backend`.
- 76 test functions across unit, integration and module tests.

Main test areas:

| Area | Files |
| --- | --- |
| API | `tests/test_api.py` |
| Pipeline | `tests/test_pipeline.py` |
| Extraction | `tests/test_extraction.py` |
| Intelligence modules | `tests/test_intelligence_modules.py` |
| Backlog | `tests/test_backlog.py` |
| MDS | `tests/unit/test_mds.py` |
| Problem dimensions | `tests/intelligence/problem_dimensions/**` |
| Portfolio | `tests/intelligence/portfolio/**` |

Problem-dimension tests cover:

- feature builder;
- coefficient generation;
- FAMD reproducibility;
- publish gates;
- no identifier leakage;
- dimension API;
- LLM interpretation;
- factor prioritisation;
- backlog factor coverage.

### 21.2 Commands

```bash
make test
make lint
make build
```

- `make test` runs pytest.
- `make lint` runs Ruff on backend, tests and pipelines, then frontend ESLint.
- `make build` builds the frontend.

Ruff configuration:

```text
line-length = 120
target-version = py311
select = E, F, I, B, UP, SIM
ignore = E501
```

Frontend ESLint may require the additional config dependencies described in `docs/gcp-migration.md`.

### 21.3 Quality safeguards in the product

- feature-quality gates block FAMD on critical failures;
- forbidden-field checks prevent target leakage;
- deterministic validators reject ungrounded narrative claims;
- publish gates require approved dimensions;
- missing data statuses are preserved;
- evidence spans must be exact substrings;
- CSV export neutralises formula injection;
- audit events record privileged actions.

---

## 22. Docker and GCP Deployment Assets

### 22.1 Docker images

| Image | Purpose |
| --- | --- |
| `docker/Dockerfile.backend` | FastAPI backend on Python 3.13 slim. Runs as non-root user. |
| `docker/Dockerfile.frontend` | Multi-stage Node build plus Nginx runtime. |
| `docker/Dockerfile.worker` | Batch worker for Cloud Run Jobs. |

### 22.2 Nginx

`docker/nginx.conf`:

- serves the built frontend;
- proxies `/api/` to `${BACKEND_URL}`;
- sets a 300-second proxy read timeout;
- caches assets;
- falls back to `index.html` for client-side routing.

### 22.3 Cloud Build

`cloudbuild.yaml` builds, tests, pushes and deploys images. It is a **runtime smoke target**, not a production data platform, because the backend still uses SQLite on ephemeral Cloud Run disk. See `docs/gcp-migration.md`.

### 22.4 Terraform

`infra/terraform` provisions:

- required APIs;
- versioned GCS bucket with lifecycle rules;
- BigQuery datasets;
- Artifact Registry repository;
- backend, worker and Workflows service accounts;
- least-privilege IAM roles;
- Secret Manager secret for Gemini;
- Cloud Run backend service;
- Cloud Run frontend service;
- Cloud Run worker job;
- feedback and backlog Cloud Workflows.

Terraform creates no secret version. Images are optional variables; empty image variables skip service/job creation.

Workflows:

```text
workflows/feedback_pipeline.yaml
workflows/backlog_validation.yaml
```

### 22.5 Current local-to-GCP gap

| Area | Local PoV | GCP target | Status |
| --- | --- | --- | --- |
| Raw feedback | Local object store | GCS versioning | GCS adapter exists, not integration-tested |
| Analytics store | SQLite | BigQuery | Read-only adapter; SQLite remains write store |
| Orchestration | In-process threads | Workflows + Cloud Run Jobs | Scaffolding exists; worker still runs whole pipeline |
| Auth | None | IAM + app roles | Missing |
| Secrets | `.env` | Secret Manager | Secret resource exists; no version |
| Observability | JSON logs | Cloud Logging/Monitoring | Logs ready, metrics/alerts partial |
| Durable uploads/reports | Local disk | GCS | Not yet wired |
| Tests | Local pytest | Unit + integration + contract | GCP integration tests missing |

### 22.6 Production blockers

1. Complete the BigQuery write path for all operational writes.
2. Persist shared run state across Cloud Run Jobs.
3. Add authentication and authorisation for review endpoints.
4. Store backlog uploads and reports durably in GCS.
5. Add bounded retries, dead-letter handling and cancellation.
6. Create and mount the Secret Manager secret version.
7. Wire frontend/backend hostnames, CORS and cookies.
8. Replace ephemeral `/tmp` SQLite with durable storage.

**Do not claim a real GCP deployment without running the Terraform, Cloud Build and verification steps against a real project.**

---

## 23. Security, Privacy and Governance

### 23.1 Privacy

- PII is redacted before persistence.
- Redaction labels are recorded.
- Raw text is only used inside the controlled pipeline.
- Quarantined rows retain reasons.
- The dataset is synthetic, and the UI keeps that warning visible.

### 23.2 Prompt safety

- LLM prompts treat serialized evidence as untrusted data, not instructions.
- Narrative outputs are structured and validated.
- Technical IDs are rejected in prose.
- Causal and unverified claims are rejected.
- Missing data cannot be described as zero.

### 23.3 Access control

Current review endpoints trust a `reviewer` field in the request body. There is no authentication or role enforcement yet. This is a known production blocker. Do not expose raw evidence to unauthorised users.

### 23.4 Auditability

- Pipeline runs and stages are recorded.
- Ingestion manifests record source and redaction metadata.
- Review decisions are recorded.
- Dimension publications are append-only.
- Narratives and validations are append-only.
- Audit log records privileged actions.
- Versions are persisted with outputs.

### 23.5 Data governance

- Synthetic data is clearly labelled.
- Evidence is separated from inference.
- Verified risk is never inferred from text.
- Organisational priority remains a human decision.
- The system preserves contradictory evidence.
- Missingness and coverage are explicit.

### 23.6 Export safety

- CSV exports neutralise spreadsheet formula injection.
- Report downloads are generated server-side.

---

## 24. Limitations and Non-Goals

### 24.1 Analytical limitations

- The feedback dataset is synthetic.
- Sentiment is not harm, severity or risk.
- Priority is an evidence prioritisation score, not a business case.
- The risk score is an indicator, not a verified incident.
- MDS position is semantic similarity, not severity.
- FAMD factors are exploratory statistical patterns, not proven root causes.
- Semantic coherence is a deterministic concentration measure, not an LLM judgement.
- Backlog alignment is text-based and cannot know delivery cost, dependencies or regulatory obligations.
- Percentage growth is unavailable when the baseline is zero.
- Some metrics are unavailable by design rather than estimated.

### 24.2 Explicitly unavailable business measures

The portfolio serialization lists unavailable attributes, including:

- severity score;
- frustration score;
- trust score;
- churn risk;
- customer lifetime value;
- revenue at risk;
- regulatory risk score;
- security risk score;
- financial risk score;
- complaint cost;
- resolution time;
- NPS;
- CSAT.

These must not be inferred from sentiment or text.

### 24.3 Advanced analytics

Survival and conjoint analyses are guarded and disabled by default.

- Survival requires event, duration, time origin and censoring data. Feedback sentiment is not an event.
- Conjoint requires an experimental design with controlled attribute levels and choice responses. Ordinary feedback is not a design.

### 24.4 Operational limitations

- Local SQLite and background threads are suitable for a PoV, not a multi-tenant production service.
- Cloud Run local disk is ephemeral.
- BigQuery writes are incomplete.
- No authentication.
- No durable dead-letter queue.
- No production-grade retry, cancellation or tenancy isolation.

### 24.5 Documentation drift

Some repository documents still describe an older active route set and older factor semantic-coherence method. This guide follows the current code. When in doubt:

- route truth: `frontend/src/App.tsx`;
- API truth: `backend/app/api/**`;
- algorithm truth: `backend/app/intelligence/**`;
- persistence truth: `backend/app/repository.py` and `schema.py`.

---

## 25. Troubleshooting

| Symptom | Likely cause | Action |
| --- | --- | --- |
| Port already in use | Existing backend/frontend process | Stop the process or change ports. |
| `app` module not found | Backend run without Python path | Use `PYTHONPATH=backend` or `--app-dir backend`. |
| Pipeline fails at startup | Bad source, schema mismatch or storage issue | Check structured logs, `/api/v1/admin/overview` and run stages. |
| No problems in UI | First run not complete | Wait or start a run; check `/api/v1/meta/source`. |
| No factor runs | No completed feedback run or FAMD disabled | Check `ENABLE_PROBLEM_DIMENSIONS` and feedback run status. |
| Factor names missing | No LLM provider/key | Configure a provider or manually name factors. |
| Prioritisation unavailable | No structurally complete FAMD run | Complete/review a factor run first. |
| No narrative | Provider not configured or validation failed | Check provider settings, logs and narrative validation endpoint. |
| Backlog report has no findings | No validated upload or no completed feedback/factor run | Validate upload and ensure a completed feedback and factor run exist. |
| Backlog validates against problems instead of factors | No factor prioritisation run | Run prioritisation first. |
| GCS errors locally | `OBJECT_STORE=gcs` without credentials | Leave `OBJECT_STORE=local`. |
| Missing measurement looks like zero | UI or consumer ignoring status | Read `status` and `source_availability`; null is not zero. |

---

## 26. File-by-File Guide

### 26.1 Backend entry points

| File | What it does |
| --- | --- |
| `backend/app/main.py` | Creates the FastAPI app, configures JSON logging and CORS, initialises services, registers routers, handles startup seeding. |
| `backend/app/config.py` | All settings, defaults, paths and provider configuration. |
| `backend/app/models.py` | Pydantic request/response contracts. |
| `backend/app/db.py` | SQLite connection wrapper, JSON helpers and additive column migrations. |
| `backend/app/schema.py` | SQLite DDL for all tables. |
| `backend/app/repository.py` | The central persistence and read-model layer. |
| `backend/app/storage.py` | Local and GCS object-store implementations. |

### 26.2 API

| File | Prefix / area |
| --- | --- |
| `backend/app/api/routes.py` | Main routes: health, feedback, problems, taxonomy, journey, backlog, priorities, MDS, quality, admin. |
| `backend/app/api/dimension_routes.py` | `/problem-dimensions` |
| `backend/app/api/factor_routes.py` | `/factor-analysis` alias |
| `backend/app/api/mapping_routes.py` | `/mappings` |
| `backend/app/api/portfolio_routes.py` | `/problem-portfolio` |
| `backend/app/api/prioritisation_routes.py` | `/factor-prioritisation` |

### 26.3 Services

| File | Responsibility |
| --- | --- |
| `services/pipeline.py` | Feedback pipeline orchestration and publication. |
| `services/ingestion.py` | CSV parsing, validation, quarantine, PII/language integration, duplicate linking. |
| `services/backlog.py` | Backlog upload, normalisation, factor/problem validation, report generation. |
| `services/problem_dimensions.py` | FAMD run lifecycle, feature build, quality gates, fitting, review, publication, LLM naming. |
| `services/factor_prioritisation.py` | Factor priority run lifecycle and persistence. |
| `services/problem_portfolio.py` | Portfolio serialization, narrative generation and validation. |
| `services/mappings.py` | Read-only evidence graph. |
| `services/mds.py` | Theme-map orchestration and read model. |

### 26.4 Intelligence: core

| File | Responsibility |
| --- | --- |
| `intelligence/contracts.py` | Shared Pydantic models and enums. |
| `intelligence/text.py` | Normalisation, redaction, tokenisation, sentence/clause splitting. |
| `intelligence/pii.py` | PII provider abstraction and optional Presidio. |
| `intelligence/language.py` | Language detection providers. |
| `intelligence/duplicates.py` | Exact, near and repeat duplicate logic. |
| `intelligence/quality.py` | Data-quality checks. |
| `intelligence/lexicon.py` | Intents, aspects, symptoms and regex signals. |
| `intelligence/extractor.py` | Insight extraction and confidence. |
| `intelligence/providers.py` | Optional extraction providers. |
| `intelligence/embeddings.py` | Embedding providers and vector helpers. |
| `intelligence/clustering.py` | Canonical problem discovery and taxonomy mapping. |
| `intelligence/taxonomy.py` | Taxonomy loading, scoring, ancestor traversal and proposals. |
| `intelligence/retrieval.py` | Hybrid dense/sparse retrieval. |
| `intelligence/measurement.py` | Windowed metrics and coverage/status logic. |
| `intelligence/prioritization.py` | Problem priority score and escalation. |
| `intelligence/mds.py` | Theme vectors, cosine distances and metric MDS. |
| `intelligence/advanced.py` | Guarded survival/conjoint placeholders. |

### 26.5 Intelligence: problem dimensions

| File | Responsibility |
| --- | --- |
| `problem_dimensions/feature_builder.py` | Versioned feature matrix and feature dictionary. |
| `problem_dimensions/data_quality.py` | Quality gates. |
| `problem_dimensions/preprocessing.py` | Imputation and fitting-frame preparation. |
| `problem_dimensions/famd_runner.py` | FAMD fitting and bootstrap stability. |
| `problem_dimensions/efa_runner.py` | Optional EFA comparison. |
| `problem_dimensions/coefficients.py` | Equations and relative squared-coordinate shares. |
| `problem_dimensions/diagnostics.py` | Memberships and trends. |
| `problem_dimensions/interpretation.py` | Deterministic draft definitions. |
| `problem_dimensions/publisher.py` | Publishability checks. |
| `problem_dimensions/llm/pipeline.py` | LLM nomenclature orchestration. |
| `problem_dimensions/llm/factor_equations.py` | Complete factor equation payloads and coefficient interpretation. |
| `problem_dimensions/llm/equation_serializer.py` | Equation serialization. |
| `problem_dimensions/llm/taxonomy_context.py` | Banking taxonomy context. |
| `problem_dimensions/llm/narrative_agent.py` | LangChain factor narrative agent. |
| `problem_dimensions/llm/validation.py` | LLM output validation. |
| `problem_dimensions/llm/gemini_client.py` | Gemini client and provider handling. |
| `problem_dimensions/llm/nomenclature.py` | Candidate naming and review flow. |
| `problem_dimensions/llm/aggregation.py` | Cross-review aggregation. |
| `problem_dimensions/llm/sequential.py` | Sequential factor interpretation. |

### 26.6 Intelligence: factor prioritisation and portfolio

| File | Responsibility |
| --- | --- |
| `intelligence/factor_prioritisation/data.py` | Loads persisted FAMD evidence. |
| `intelligence/factor_prioritisation/scoring.py` | Component scorers. |
| `intelligence/factor_prioritisation/calculator.py` | Final score, status, ranking and explanation. |
| `intelligence/portfolio/serialization.py` | Deterministic portfolio serialization and narrative context. |
| `intelligence/portfolio/narrative.py` | Gemini narrative provider. |
| `intelligence/portfolio/validation.py` | Deterministic narrative validation. |
| `intelligence/portfolio/contracts.py` | Narrative contracts. |

### 26.7 Frontend

| File | Responsibility |
| --- | --- |
| `frontend/src/App.tsx` | Route table. |
| `frontend/src/components/Layout.tsx` | Sidebar, top bar, synthetic warning and metadata. |
| `frontend/src/components/ui.tsx` | Cards, badges, stats, empty states, spinners. |
| `frontend/src/components/Charts.tsx` | Chart helpers. |
| `frontend/src/components/FilterBar.tsx` | Filter controls. |
| `frontend/src/components/MappingGraph.tsx` | Graph rendering. |
| `frontend/src/lib/api.ts` | API client, errors, idempotent POST, form upload, download. |
| `frontend/src/lib/types.ts` | 1,249-line API/domain type definitions. |
| `frontend/src/lib/useFetch.ts` | Fetch hook with loading/error/reload. |
| `frontend/src/lib/format.ts` | Number/date formatting. |
| `frontend/src/lib/mappingGraph.ts` | Graph layout helpers. |
| `frontend/src/pages/*.tsx` | Analytical screens listed in section 17. |

### 26.8 Supporting assets

| Path | Purpose |
| --- | --- |
| `taxonomy/banking_taxonomy_v1.yaml` | Versioned banking-app taxonomy. |
| `scripts/generate_feedback_dataset.py` | Deterministic synthetic dataset generation. |
| `scripts/gcp_deploy.sh` | GCP deployment helper. |
| `scripts/gcp_sql.sh` | BigQuery SQL helper. |
| `scripts/gcp_upload_and_run.sh` | Upload and run helper. |
| `scripts/gcp_teardown.sh` | Teardown helper. |
| `pipelines/jobs/run_pipeline.py` | Batch worker CLI. |
| `tests/fixtures/` | Test fixtures. |
| `tests/integration/` | Integration tests. |
| `tests/unit/` | Unit tests. |

---

## 27. Suggested Reading Path

### For business readers

1. Section 1-4 of this document.
2. `prioritization.md`.
3. `docs/algorithms-and-ui-calculations.md`, especially the UI page sections.
4. The UI pages **Customer problems**, **Factor analysis**, **Prioritization**, **Narrative serialization** and **Backlog validation**.

### For engineers new to the codebase

1. `backend/app/main.py` and `backend/app/config.py`.
2. `backend/app/repository.py` and `backend/app/schema.py`.
3. `backend/app/services/pipeline.py` and `backend/app/services/ingestion.py`.
4. `backend/app/intelligence/clustering.py` and `taxonomy.py`.
5. `backend/app/intelligence/measurement.py` and `prioritization.py`.
6. `backend/app/intelligence/mds.py`.
7. `backend/app/services/problem_dimensions.py` and `intelligence/problem_dimensions/**`.
8. `backend/app/intelligence/factor_prioritisation/**`.
9. `backend/app/services/backlog.py`.
10. `frontend/src/App.tsx`, then the pages.

### For reviewers and auditors

1. `docs/gcp-migration.md`.
2. `docs/problem_dimension_interpretation.md`.
3. `docs/problem_portfolio.md`.
4. `docs/factor_analysis.md`.
5. The tests under `tests/intelligence/problem_dimensions/**` and `tests/intelligence/portfolio/**`.
6. `backend/app/intelligence/portfolio/validation.py` and `problem_dimensions/llm/validation.py`.
7. `backend/app/db.py` migrations and `backend/app/schema.py`.

---

## Final Assessment

This is a well-structured, unusually explicit PoV. Its strongest qualities are:

- clear separation between evidence, inference, narrative and human decision;
- explicit handling of missing data, duplicates and quarantine;
- versioned runs, methodology, prompts and publications;
- deterministic, inspectable formulas for measurement, priority, FAMD and factor ranking;
- strong guardrails against LLM overreach;
- a read-only evidence graph connecting feedback to backlog;
- meaningful test coverage for the analytical layers.

Its main production gaps are equally clear:

- SQLite remains the write store;
- cloud orchestration and BigQuery writes are incomplete;
- authentication and authorisation are missing;
- some documentation is stale relative to the current route table and scoring implementation;
- the bundled data is synthetic and cannot support real business conclusions.

Used within those boundaries, the project is a strong foundation for evidence-traceable customer-problem discovery and backlog validation, and a credible base for a production migration.
