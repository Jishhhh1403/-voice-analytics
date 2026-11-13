# Baseline Assessment

Assessment date: 2026-11-06  
Repository: `/home/ltcctoiet/dev/analytics/voice-analytics`  
Scope: current implementation before Project Evolution changes.

This document records what the system actually does today. It is the Phase 0
baseline used to avoid redesigning components that already work and to make the
measurement, evaluation and prioritisation changes auditable.

---

## 1. Runtime and architecture

- **Backend:** FastAPI application in `backend/app/main.py`, API prefix `/api/v1`.
- **Operational store:** SQLite at `DATABASE_PATH=./data/local/bci.db`.
- **Object store:** local immutable object store by default (`OBJECT_STORE=local`); GCS adapters exist behind the same interface.
- **Read analytics:** SQLite by default; optional read-only BigQuery adapter in `backend/app/analytics/`.
- **Frontend:** React + TypeScript + Vite in `frontend/src`.
- **Extraction default:** deterministic rules (`EXTRACTION_PROVIDER=rules`).
- **Embedding default:** local TF-IDF + TruncatedSVD (`EMBEDDING_PROVIDER=local`, 96 dimensions).
- **Clustering default:** legacy signature/centroid clustering (`CLUSTERING_PROVIDER=legacy`).
- **LLM and cloud services are optional.** Deterministic fallbacks are required when providers are unavailable.
- **GCP deployment is scaffolding only.** Cloud Run/Build/BigQuery files exist, but local SQLite remains the working execution path.

### Execution paths

```text
Feedback CSV
  -> validate_source
  -> module_a_ingest
  -> module_b_extract
  -> module_c_discover
  -> module_d_map
  -> measurement_engine
  -> priority_engine
  -> module_e_publish

Backlog CSV
  -> normalise/profile
  -> hybrid retrieval
  -> relationship decision
  -> coverage matrix
  -> validation report
```

The feedback pipeline is orchestrated by `backend/app/services/pipeline.py`.
Backlog validation is orchestrated by `backend/app/services/backlog.py`.

---

## 2. Data model and persistence

Core feedback tables:

- `pipeline_runs`, `pipeline_stages`, `ingestion_manifests`
- `feedback_records`, `feedback_quarantine`, `extracted_insights`
- `customer_problems`, `problem_evidence`, `problem_clusters`
- `taxonomy_nodes`, `problem_mappings`, `taxonomy_proposals`
- `feedback_duplicate_candidates`, `data_quality_reports`
- `problem_relationships`, `problem_symptoms`, `problem_journey_mappings`

Measurement and decision tables:

- `problem_metrics_daily`
- `problem_measurement_snapshots`
- `problem_priority_snapshots`
- `scoring_methodology_versions`
- `model_execution_history`
- `human_review_decisions`

Backlog/report tables:

- `backlog_uploads`, `backlog_items`
- `validation_runs`, `validation_reports`, `validation_findings`
- `backlog_problem_candidates`, `backlog_coverage_matrix`
- `review_decisions`, `report_reviews`

Guarded advanced analytics tables exist but are not active in the UI:

- `survival_analysis_results`
- `conjoint_analysis_results`

Schema creation and in-place migrations are in `backend/app/schema.py` and
`backend/app/db.py`. The schema was verified against the legacy SQLite schema.

---

## 3. Current algorithm inventory

| Area | Current implementation | Key thresholds/defaults |
| --- | --- | --- |
| Source validation | Object stat, SHA-256, size guard | 25 MB feedback, 10 MB backlog |
| CSV parsing | UTF-8/BOM, delimiter sniff, schema checks | Max 5000 feedback rows |
| PII redaction | Ordered regex recognizers, optional Presidio | `PII_PROVIDER=regex` |
| Language detection | Script/stopword heuristic, optional langdetect/fastText | `LANGUAGE_DETECTION_PROVIDER=heuristic` |
| Exact duplicates | SHA-256 fingerprint of normalized lowercase text | - |
| Near-duplicates | 3-token shingles, 64 MinHash permutations, 16-band LSH, Jaccard | `NEAR_DUPLICATE_THRESHOLD=0.85` |
| Repeat complaints | Same customer + lexical problem identity + time window | 30 days |
| Duplicate policy | Linked, never discarded | `linked_not_discarded` |
| Data quality | Explicit PASS/WARN/FAIL/NOT_AVAILABLE checks | - |
| Insight extraction | Rules lexicons, clause splitting, rule reconciliation | 38 intents, 44 aspects, 38 symptoms |
| Sentiment | Weighted keyword score | `> 0.4` positive, `< -0.4` negative |
| Insight confidence | Linear signal-count formula | Capped at 0.95 |
| Embeddings | TF-IDF + TruncatedSVD + L2 normalization | 96 dimensions |
| Problem discovery | Signature groups, Union-Find, centroid cosine, medoid | Similarity `0.64`, merge cosine `min(0.9, threshold + 0.18)` |
| Taxonomy mapping | Weighted lexical score + embedding fallback + open-set proposals | Accept `0.55`, semantic `0.45`, open-set `0.35` |
| Hybrid retrieval | Dense cosine + sparse TF-IDF cosine, row-normalized | Dense `0.6`, sparse `0.4`, top `8` |
| Backlog alignment | `0.35*max(semantic, lexical) + 0.25*node + 0.20*intent + 0.20*symptom_coverage` | - |
| Measurement | Deterministic aggregation with status/provenance | 90-day window; 30+30 trend |
| Prioritisation | Five-component weighted score + escalation rules | 0.30/0.30/0.15/0.15/0.10 |
| Advanced methods | Survival/conjoint only with required inputs | Disabled in UI |

---

## 4. Measurement baseline

Implemented in `backend/app/intelligence/measurement.py`.

Current snapshot metrics:

- `evidence_volume`
- `distinct_customers`
- `negative_share`
- `repeat_complaint_count`
- `source_diversity`
- `assessment_velocity_delta`

Current window metadata:

- Main window: `MEASUREMENT_WINDOW_DAYS=90`
- Trend baseline: previous 30 days
- Trend current: latest 30 days

**Critical baseline defect:** the main metrics currently aggregate *all linked
evidence*, even though their snapshot metadata says 90 days. Only
`assessment_velocity_delta` actually splits data into baseline/current windows.
This mixes lifetime and windowed values and makes every main metric
inconsistent with its provenance.

Other baseline limitations:

- No explicit lifetime/90-day/30-day/previous-30 values for all core metrics.
- No volume/customer/negative growth metrics.
- Zero and missing values are not fully distinguished, especially for windows
  that fall outside source date coverage.
- Priority snapshots store `NULL` measurement window start/end.
- Risk terms produce a numeric business-risk component, but detected risk
  indicators are not separated from human-verified risk.

---

## 5. Prioritisation baseline

Implemented in `backend/app/intelligence/prioritization.py`.

Weights:

- Customer impact: `0.30`
- Business risk: `0.30`
- Operational impact: `0.15`
- Trend: `0.15`
- Strategic fit: `0.10`

Observable behaviour:

- Component scores and total score are persisted.
- Missing trend data falls back to `0.5` while adding the metric to `missing_metrics`.
- Business risk is inferred from risk terms and negative share.
- Escalation occurs when business risk is above `0.75`, or when trend and customer impact are both high.
- Priority is explicitly customer-evidence prioritisation, not organisational approval.

Baseline limitations:

- Risk indicators are presented as a business-risk score without a verified-risk distinction.
- Supporting evidence contains counts, but not detected risk terms or verification state.
- Priority snapshot window fields are empty.
- Missing measurements still use numeric fallbacks in some components, which can make scores look more certain than the data supports.

---

## 6. API and UI baseline

Active frontend routes:

- `/` -> Journey explorer
- `/journey`
- `/problems`
- `/problems/:problemId`
- `/backlog`
- `/reports/:reportId`

`OverviewPage.tsx` and `RunsPage.tsx` exist but are not routed or displayed.

Relevant APIs:

- `GET /health`, `GET /meta/source`
- `GET/POST /feedback-sources`, `POST /feedback-pipelines`
- `GET /feedback-pipelines`, `GET /feedback-pipelines/{run_id}`
- `GET /journey`, `GET /problems`, `GET /problems/{id}`
- `GET /problems/{id}/measurement`, `GET /problems/{id}/priority`
- `GET /priorities`, `GET /duplicates`, `GET /data-quality`
- `POST /backlog-validations`, `GET /backlog-validations`, `GET /reports/{id}`
- `GET /admin/overview`

The problem detail UI displays measurement snapshots, priority components,
escalation status, supporting feedback, and computed insight signals. Missing
measurement snapshots fall back to direct counts from linked evidence.

---

## 7. Verification baseline

Commands and current results:

```bash
ruff check backend tests       # clean
python -m pytest -q            # 21 passed
cd frontend && npm run build   # passed
```

`npm run lint` is not available because the frontend has no ESLint config.

Latest observed demo pipeline run: `RUN-20261106072706-8a981e`

- Accepted feedback: 1800
- Exact duplicates: 409
- Near-duplicate links: 511
- Repeat-complaint links: 2
- Insights: 2447
- Problems: 162
- Mapped: 160
- Unmapped/open-set proposals: 2
- Evidence links: 1577
- Measurement snapshots: 972
- Prioritised problems: 162
- Escalations: 5

Observed repetition example: `CP-a5082b92f9b4c2` has 64 linked evidence rows
but only 18 unique evidence spans; its top span repeats 39 times. This is why
duplicates must be linked and evidenced rather than silently discarded.

---

## 8. Known gaps to address

1. **Measurement correctness**
   - All primary metrics must use their declared window.
   - Lifetime, 90-day, 30-day, and previous-30 values must be explicit.
   - Growth metrics need minimum-data guards.
   - Missing/invalid/out-of-coverage windows must return `NO_DATA` or
     `INSUFFICIENT_DATA`, not zero.
   - Priority snapshots need measurement provenance windows.

2. **Risk semantics**
   - Separate detected risk indicators from verified risk.
   - Expose detected terms, evidence, and verification state.
   - Do not imply that textual risk terms are confirmed incidents.

3. **Evaluation**
   - No annotation dataset, evaluation harness, or model-quality dashboard exists.
   - HDBSCAN is configured in settings but not implemented.
   - `TAXONOMY_CROSS_ENCODER_ENABLED` exists but is unused.

4. **Discovery and mapping**
   - Current clustering is lexical/embedding centroid based.
   - Open-set proposals are persisted but human-review workflow is limited.
   - Taxonomy cross-encoder path is not implemented.

5. **Prioritisation transparency**
   - Missing metrics still influence scores via fallbacks.
   - Tie-breaking and sensitivity to weights are not exposed.

6. **Decision support**
   - Backlog validation is evidence coverage, not an approval engine.
   - Coverage and priority are displayed separately and must stay separate.

---

## 9. Phase 0 conclusion

The platform already has the required separation between ingestion,
extraction, discovery, mapping, measurement, prioritisation, and backlog
validation. The highest-value immediate correction is measurement integrity:
metrics currently claim a 90-day window while counting lifetime evidence.
Priority calculations then consume those mixed values.

Phase 1 should therefore make windows explicit and consistent, add growth
metrics with minimum-data guards, separate risk indicators from verified risk,
and persist measurement provenance on priority snapshots before moving to the
evaluation framework and semantic-discovery upgrades.

---

## 10. Post-baseline implementation status

Phase 1 changes implemented on 2026-11-06 after this baseline was recorded:

- Core measurements are now emitted for lifetime, configured 90-day, current
  30-day and previous 30-day windows, with canonical aliases for compatibility.
- Growth metrics and negative-share change are calculated with coverage and
  minimum-data guards.
- Uncovered windows return `NO_DATA` instead of zero; partially covered windows
  return `PARTIAL`.
- Prioritisation consumes stored measurement snapshots and records measurement
  status, risk indicators, verification state, data completeness and the
  measurement window on each priority snapshot.
- Risk term scores are explicitly labelled as indicators; verification defaults
  to `NOT_VERIFIED`.
- The measurement API now returns snapshots from the latest measurement run only.
- Regression tests cover window counts, coverage gaps, growth denominators,
  risk separation and priority provenance.

Latest verification after Phase 1:

```bash
ruff check backend tests       # clean
python -m pytest -q            # 23 passed
cd frontend && npm run build   # passed
```

Latest pipeline run: `RUN-20261106101416-ec07cb` with 5022 measurement
snapshots across 31 metric names.
