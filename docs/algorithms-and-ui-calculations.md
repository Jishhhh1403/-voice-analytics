# Algorithms and UI Calculations

This document explains the algorithms currently wired into the running application and traces every value shown in the active React UI back to its API field, database value, or formula.

It is written for two audiences:

- **Engineers** who need to know which code path produces a number.
- **Analysts/product owners** who need to know what a UI label does and does not mean.

Companion documents:

- `docs/pipeline-algorithms.md` - deeper implementation notes, diagrams and parameter tables for the feedback/backlog pipelines.
- `docs/gcp-migration.md` - production migration boundaries.

> Source of truth: `backend/app/services/*`, `backend/app/intelligence/*`, `backend/app/repository.py`, `backend/app/api/routes.py`, and `frontend/src/*`.
>
> Active UI routes: `/`, `/journey`, `/problems`, `/problems/:problemId`, `/backlog`, `/reports/:reportId`.
> `OverviewPage.tsx` and `RunsPage.tsx` still exist in the repository but are not routed or displayed.

---

## 1. End-to-end flow

```text
Feedback CSV
  -> validate_source (object stat + SHA-256 + size guard)
  -> module_a_ingest (PII, language, quality, exact/near/repeat duplicate links)
  -> module_b_extract (intent/aspect/symptom/sentiment evidence)
  -> module_c_discover (embedding + signature clustering into customer problems)
  -> module_d_map (taxonomy mapping or open-set proposal)
  -> measurement_engine (windowed problem metrics)
  -> priority_engine (transparent weighted score)
  -> module_e_publish (daily aggregates + run summary)
  -> API -> Journey / Problems / Problem detail UI

Backlog CSV
  -> module_f_normalise (parse, validate, profile backlog items)
  -> module_g_validate (hybrid retrieval + rule-based relationship decision)
  -> validation report
  -> API -> Backlog / Report UI
```

The feedback pipeline is started from `backend/app/services/pipeline.py`. Backlog validation is started from `backend/app/services/backlog.py`.

---

## 2. Algorithm inventory

| Area | Algorithm | Key parameters | Main implementation | Used by |
| --- | --- | --- | --- | --- |
| Source validation | Object metadata + SHA-256 + byte-size limit | `max_feedback_bytes` (25 MB) | `pipeline.py::execute` | Pipeline stage `validate_source` |
| CSV parsing | UTF-8/BOM decode, `csv.Sniffer`, `DictReader` | Comma preferred, Excel fallback | `ingestion.py::parse_feedback_csv` | Module A |
| Schema validation | Required columns, row cap | `pipeline_max_rows` (25000) | `ingestion.py` | Module A |
| Timestamp parsing | ISO-8601 parse, `Z` -> UTC, naive -> UTC | - | `ingestion.py::_parse_timestamp` | Module A |
| Rating validation | `int(float(value))`, range 1-5 | - | `ingestion.py::_parse_rating` | Module A |
| Text normalization | Unicode NFKC, remove zero-width/NBSP, collapse whitespace | - | `text.py::normalize_text` | Module A/B |
| PII redaction | Ordered regex recognizers; optional Presidio fallback | `PII_PROVIDER=regex|presidio|hybrid` | `text.py::redact_pii`, `pii.py` | Module A |
| Language detection | Script + stopword heuristic; optional langdetect/fastText | `LANGUAGE_DETECTION_PROVIDER` | `language.py` | Module A |
| Exact duplicate linking | SHA-256 fingerprint of normalized lowercase text | - | `ingestion.py::_fingerprint` | Module A |
| Near-duplicate linking | 3-token shingles + 64 MinHash permutations + 16-band LSH + exact Jaccard | `NEAR_DUPLICATE_THRESHOLD=0.85`, min 5 tokens | `duplicates.py` | Module A |
| Repeat complaint linking | Same customer + lexical problem identity + time window | `REPEAT_COMPLAINT_WINDOW_DAYS=30` | `duplicates.py` | Module A, measurement, priority |
| Data quality | Explicit PASS/WARN/FAIL/NOT_AVAILABLE checks | - | `quality.py` | Module A/API |
| Segmentation | Sentence split, clause split, reporting-prefix stripping | Min sentence length 2; clause 8 | `text.py`, `extractor.py` | Module B |
| Lexicon matching | Regex entity match, earliest + longest wins | 38 intents, 44 aspects, 38 symptoms | `lexicon.py::match_entities` | Module B/F/G |
| Aspect/intent reconciliation | Module-aware aspect preference/clearing | - | `extractor.py` | Module B |
| Sentiment | Weighted positive/negative keyword counting | Thresholds `>0.4`, `<-0.4` | `lexicon.py::sentiment` | Module B |
| Emotion/effort/outcome | Ordered regex classifiers | - | `lexicon.py` | Module B |
| Insight confidence | Linear signal-count formula, capped 0.95 | - | `extractor.py` | Module B/UI |
| LLM extraction | Structured prompt + JSON parse + rule fallback | Temperature 0; exact-substring guard | `providers.py` | Module B (optional) |
| Embeddings | TF-IDF + TruncatedSVD + L2 normalize; optional ST/Gemini/Vertex | Default 96 dimensions | `embeddings.py` | Module C/G |
| Problem discovery | Signature grouping + Union-Find + centroid cosine + medoid + majority vote | Merge cosine `min(0.9, threshold+0.18)` | `clustering.py` | Module C |
| Taxonomy mapping | Weighted lexical score, embedding fallback, open-set proposals | Accept 0.55, semantic 0.45, open-set 0.35 | `taxonomy.py`, `clustering.py` | Module D/UI |
| Problem co-occurrence | Same-customer problem pairs | Confidence `min(0.9, 0.3 + 0.1*count)` | `pipeline.py::_cooccurrence_relationships` | API only |
| Measurement | Windowed deterministic aggregation with status/provenance | Lifetime, 90-day, 30-day, previous 30-day | `measurement.py` | UI problem detail |
| Prioritisation | Weighted five-component score + escalation rules | 0.30/0.30/0.15/0.15/0.10 | `prioritization.py` | UI problem detail |
| Backlog profiling | Regex intents/aspects/symptoms + product-area/alias + `best_node(2.0)` | - | `backlog.py::_profile` | Module F |
| Hybrid retrieval | Dense embedding cosine + sparse TF-IDF cosine, row-normalized and blended | Dense 0.6 / sparse 0.4; top 8 | `retrieval.py` | Module G |
| Backlog alignment | `0.35*max(semantic, lexical) + 0.25*node + 0.20*intent + 0.20*coverage` | - | `backlog.py::_validate` | Report UI |
| Relationship decision | Rule tree over node, coverage, intent and similarity | - | `backlog.py::_relationship` | Report UI |
| Overall alignment | Priority of findings + evidence gates | - | `backlog.py::_overall` | Report UI |
| Coverage gaps | Problems not addressed by any finding and evidence >= 5 | Top 12 | `backlog.py` | Report UI |
| Guarded advanced analytics | Survival/conjoint only when required inputs exist | - | `advanced.py` | Not active in UI |

---

## 3. Ingestion and validation (Module A)

### 3.1 Source and CSV validation

Implemented in `backend/app/services/pipeline.py` and `backend/app/services/ingestion.py`.

- The source object must exist and be no larger than `MAX_FEEDBACK_BYTES` (default 25 MB).
- The pipeline records object generation, size and SHA-256 in the stage metrics.
- CSV text is decoded as UTF-8 with optional BOM.
- `csv.Sniffer().sniff(text[:4096], delimiters=",")` detects delimiter; fallback is `csv.excel`.
- All required columns must be present.
- Row processing stops with an error after `PIPELINE_MAX_ROWS` (default 25000).

Required feedback columns:

```text
feedback_id, submitted_at, source_type, source_channel, platform,
app_version, language, synthetic_customer_ref, rating_1_to_5,
feedback_title, feedback_text, is_synthetic
```

A row is rejected only for invalid input, not because it repeats another row. The only rejections are missing/empty feedback text, bad timestamp, bad rating, too-short text after redaction, or duplicate source IDs within one upload.

### 3.2 Normalization

`text.py::normalize_text` applies:

1. Unicode NFKC normalization.
2. Zero-width space removal and NBSP replacement.
3. `\r`, `\n`, `\t` collapsed to spaces.
4. Repeated whitespace collapsed.

### 3.3 PII redaction

`text.py::redact_pii` applies these patterns in order and replaces matches with `[LABEL]`:

```text
EMAIL, CARD, PHONE, AADHAAR, ACCOUNT, IFSC_ACCOUNT, UPI_ID, NAME, URL
```

Then any bare digit run of length 9 or more is replaced with `[NUMBER]`.

`pii.py` optionally uses Presidio with banking recognizers for IFSC, UPI, Aadhaar and account numbers. If Presidio is missing, fails, or the language is unsupported, the deterministic regex path is used. The result records `provider_used`.

The original text is retained as `feedback_text_original` for provenance, but all analytics, evidence, API and UI flows use `feedback_text_redacted`.

### 3.4 Language detection

`language.py` returns `(language, confidence, supported, provider)`.

Heuristic path:

- Non-Latin scripts map directly to `hi`, `ta`, `te`, `bn`, or `mr` with confidence 0.75.
- Otherwise stopword hit ratio is computed for English and Hindi.
- If two or more Hinglish markers are present, language is `hinglish` with confidence `max(0.4, min(0.85, best_score + 0.2))`.
- Otherwise confidence is `min(0.95, 0.35 + 2 * best_score)`.

Optional `langdetect` and `fastText` providers are supported. Any failure falls back to the heuristic.

### 3.5 Exact duplicates

`_fingerprint(text) = sha256(normalize_text(text).lower())`.

The first record with a fingerprint becomes the anchor. Later records with the same fingerprint are linked as exact duplicates with similarity 1.0. They are persisted as relationships and are never dropped.

### 3.6 Near-duplicates

`duplicates.py::detect_duplicate_relationships`:

1. Tokenize redacted text with `[a-z0-9][a-z0-9'-]*`.
2. Skip records with fewer than `NEAR_DUPLICATE_MIN_TOKENS` (default 5).
3. Build 3-token shingles.
4. Compute a 64-permutation MinHash signature using BLAKE2b seeded hashes.
5. Split the signature into 16 bands of 4 rows.
6. Candidate pairs from the same LSH bucket are checked with exact Jaccard similarity.
7. Keep a pair only when `Jaccard >= NEAR_DUPLICATE_THRESHOLD` (default 0.85); exact 1.0 pairs are left to exact-duplicate handling.

Near-duplicate similarity is the exact Jaccard value stored on the relationship.

### 3.7 Repeat complaints

Repeat detection is separate from duplicate detection:

- Requires `synthetic_customer_ref`.
- Builds a lexical problem identity: unique tokens longer than 3 characters, sorted, first 24.
- Groups by `(customer_ref, identity)`.
- Within each group, links a record to the most recent earlier record if the gap is within `REPEAT_COMPLAINT_WINDOW_DAYS` (default 30).

This creates repeat-complaint links used by measurement and prioritisation. It does not remove the record.

### 3.8 Data quality checks

`quality.py` returns explicit statuses:

| Check | Status rule |
| --- | --- |
| `empty_feedback` | `FAIL` if any raw row has empty text, else `PASS` |
| `unexpected_text_length` | `WARN` if any accepted text is below 3 or above 5000 chars |
| `corrupted_text` | `WARN` if replacement/control characters are found |
| `missing_or_invalid_timestamps` | `FAIL` if rejected rows mention `submitted_at` |
| `source_distribution` | `WARN` if one source has >= 90% share and more than one source exists |
| `unsupported_language` | `WARN` if any accepted language is outside the supported set |
| `duplicate_rate` | `WARN` if `duplicates / (accepted + duplicates) >= 0.25` |
| `invalid_encoding` | `FAIL` if any rejection mentions UTF-8 |

The duplicate policy is always recorded as `linked_not_discarded`.

---

## 4. Insight extraction (Module B)

Implemented in `backend/app/intelligence/extractor.py`, `lexicon.py` and `providers.py`.

### 4.1 Segmentation

- Sentence boundaries: `[.!?]+` followed by whitespace/end, or `;+`.
- Clause boundaries: sentence boundaries plus connectors such as `but`, `although`, `however`, `whereas`, `while`, `also`, `additionally`, `on top of that`, `another thing is that`.
- Minimum sentence length is 2 characters; minimum clause length is 8.
- Repeated reporting prefixes such as `today,`, `also,`, `I wanted to share this:` are stripped.

### 4.2 Lexicon matching

The lexicon contains regex patterns for intents, aspects and symptoms.

For each entity, the best match score is:

```text
score = (10000 - min(match_start, 9999)) * 100 + match_length
```

This means **earliest match wins; for the same start, longest match wins**. Entities are sorted by this score, and the first is the primary anchor. This is deterministic and not probabilistic.

### 4.3 Extraction flow

For each feedback record:

1. Global context = title + redacted text.
2. Find global aspect and intent from that context.
3. For each sentence and clause:
   - Clean reporting filler.
   - Require at least 2 tokens.
   - Match local aspects, intents and symptoms.
   - Skip clauses with no local anchor.
   - Reconcile the local aspect with the intent's `node_hint` module.
   - Inherit global aspect/intent when missing.
   - Skip clauses with no aspect, symptom or intent.
4. Compute sentiment, emotion, effort and outcome.
5. Decide `is_problem`.
6. Build a neutral customer statement if it is a problem.
7. Compute insight confidence and field confidence.
8. Keep the insight only if `evidence_span` is an exact substring of the redacted source.

### 4.4 Sentiment

`lexicon.sentiment`:

- Each negative hit subtracts 1.0; a preceding intensifier subtracts another 0.5.
- Each positive hit adds 1.0; a preceding negator subtracts 1.0; a preceding intensifier adds 0.25.
- If both positive and negative hits exist and `abs(score) <= 1.5`, label is `mixed`.
- Else `score > 0.4` -> `positive`; `score < -0.4` -> `negative`; otherwise `neutral`.

### 4.5 Emotion, effort, outcome

- Emotion: ordered lookup for frustration, confusion, anxiety, disappointment, satisfaction.
- Effort: high > medium > low > unknown.
- Outcome: abandoned > blocked > failed > workaround_used > completed > unknown.

### 4.6 Is-problem rule

An insight is a problem when any of these is true:

- Sentiment is `negative` or `mixed`.
- A symptom is present and sentiment is not `positive`.
- Outcome is `blocked`, `failed` or `abandoned`.

### 4.7 Confidence

```text
signal_count = (aspect exists) + (symptom exists) + (intent exists)
             + (sentiment is not neutral)

confidence = min(0.95, 0.46 + 0.13 * signal_count + 0.06 if is_problem)
```

Field confidence values are fixed heuristics:

- Intent: 0.58 if present, else 0.30.
- Aspect: 0.62 if present, else 0.30.
- Reported problem: overall confidence.
- Symptom: 0.66 if present, else 0.25.
- Sentiment: `min(0.9, 0.45 + 0.12 * (positive_hits + negative_hits))`.
- Emotion/effort/outcome: around 0.52-0.55 if detected, else 0.20.
- Evidence span: 1.0.

### 4.8 LLM path

If `EXTRACTION_PROVIDER` is `gemini` or `openai_compatible`:

- A fixed JSON prompt (`extraction-2.0`) is sent with temperature 0.
- Returned insights must have an evidence span that is an exact substring of the redacted text.
- Invalid or missing records fall back to the deterministic rule extractor.
- LLM confidence defaults to 0.7 unless field confidence is supplied.

The UI always displays the confidence that was stored, not a recalculated value.

---

## 5. Embeddings and problem discovery (Module C)

### 5.1 Embeddings

`embeddings.py::build_embedder` tries the configured provider, then falls back to the local deterministic embedder on any exception:

1. Gemini if configured with an API key.
2. Sentence Transformers if selected and installed.
3. Vertex AI if selected and project credentials are available.
4. Local TF-IDF + TruncatedSVD.

Local embedder:

```text
TfidfVectorizer(ngram_range=(1, 2), min_df=1, max_df=0.95,
                sublinear_tf=True, stop_words="english",
                strip_accents="unicode")
TruncatedSVD(n_components=max(2, min(96, n_features-1, n_samples-1)),
             random_state=42)
L2 normalize
```

Similarity is cosine similarity, computed as the dot product of L2-normalized vectors, clipped to `[-1, 1]`.

Embeddings are used for candidate retrieval and grouping support only. They are not treated as proof that two complaints are the same problem.

### 5.2 Signature grouping

Each problem insight gets a deterministic signature:

```text
journey_node_id | symptom_key
```

If the symptom is `general`:

```text
journey_node_id | general | customer_intent
```

Symptom key is derived from the reported symptom, or the symptom category, or `general`.

### 5.3 Union-Find merge

Groups are merged only when:

- Left and right have the same non-`unmapped` journey node.
- They have the same symptom key.
- Their centroid cosine similarity is at least `min(0.9, CLUSTERING_SIMILARITY_THRESHOLD + 0.18)`.

With the default `CLUSTERING_SIMILARITY_THRESHOLD=0.64`, the merge threshold is effectively `0.82`.

The merge structure uses Union-Find with path compression.

### 5.4 Representative statement and labels

- The medoid is the member with the highest mean cosine similarity to all members.
- Its reported problem becomes the representative statement.
- Aspect, symptom and intent labels are chosen by majority vote.
- Problem title is `Aspect: Symptom`, or `Aspect: Intent` when the symptom key is general.
- The canonical description is `Aspect: Symptom`.

### 5.5 Problem fields used by the UI

For each cluster, the pipeline stores:

- `evidence_count` = number of linked problem insights.
- `distinct_customers` = distinct non-null synthetic customer references.
- `negative_count` = insights labelled negative or mixed.
- `first_seen` / `last_seen` = min/max submitted timestamp among linked evidence.
- `discovery_confidence` = evidence-breadth confidence, not severity:

```text
min(0.95,
    0.35
    + 0.12 * min(4, member_count)
    + 0.08 * min(3, distinct_customers)
    + 0.05 if more than one source type)
```

`discovery_confidence` is stored but is not shown on the active problem list/detail UI.

### 5.6 Co-occurrence relationships

For each customer, all their problem IDs are collected. Every pair is counted once per customer. A relationship is stored with:

```text
confidence = min(0.9, 0.3 + 0.1 * co_occurrence_count)
```

This is descriptive co-occurrence, not causality. It is available through the API but is not shown on the active UI.

---

## 6. Taxonomy mapping (Module D)

Implemented in `backend/app/intelligence/taxonomy.py` and `clustering.py`.

### 6.1 Lexical scoring

For a taxonomy node and problem text:

| Match | Score |
| --- | --- |
| Exact display-name phrase | +3.0 |
| Exact synonym or alias phrase | +2.2 |
| Token overlap with display name/synonyms/aliases | +0.5 per token |
| Token overlap with description | +0.25 per token |
| Module node multiplier | score x 0.92 |

`best_node` returns the highest-scoring node only if the score is at least the threshold. The default ingestion threshold is 1.4; backlog profiling uses 2.0.

### 6.2 Mapping confidence and semantic fallback

For each customer problem:

1. If the problem already has a journey node, calculate the node's lexical score and use:

   ```text
   confidence = min(0.99, max(0.72, raw_score / 4))
   ```

2. If it has no node, run `best_node` over the taxonomy:

   ```text
   lexical_confidence = min(0.99, raw_score / 4)
   ```

   If `lexical_confidence >= TAXONOMY_ACCEPT_THRESHOLD` (default 0.55), accept that node.

3. Otherwise compute semantic similarity between the medoid insight vector and every feature/module nodevector built from display name, synonyms and description.

   If the best semantic similarity is at least `TAXONOMY_SEMANTIC_THRESHOLD` (default 0.45), use that node.

4. Mapping status is `candidate` if confidence is at least the accept threshold, otherwise `pending_review`.

If no node is accepted, create a taxonomy proposal. The reason is `open-set boundary` when confidence is at least `TAXONOMY_OPEN_SET_THRESHOLD` (default 0.35), otherwise `could not be confidently mapped`.

The taxonomy graph is traversed through `parent_id` with cycle protection. `path_label` returns the human-readable `Module / Feature` path.

### 6.3 Persistence used by the UI

`problem_mappings` stores the primary mapping. `problem_journey_mappings` stores the flattened module ID and feature ID. The Problems page uses `customer_problems.journey_node_id` and a taxonomy lookup for `journey_name`.

---

## 7. Measurement engine

Implemented in `backend/app/intelligence/measurement.py`.

### 7.1 Windows

Defaults:

```text
MEASUREMENT_WINDOW_DAYS = 90
TREND_BASELINE_DAYS = 30
TREND_CURRENT_DAYS = 30
```

`now` is the pipeline run time.

- Main measurement window: `now - 90 days` to `now`.
- Assessment window: `now - 30 days` to `now`.
- Baseline window: the 30 days before the assessment window.

### 7.2 Windowed metrics

Every core metric is calculated independently for four windows:

| Window | Metric suffix | Bounds |
| --- | --- | --- |
| Lifetime | `_lifetime` | All dated and undated linked evidence |
| Measurement | `_{MEASUREMENT_WINDOW_DAYS}d` (default `_90d`) | `now - 90 days` to `now` |
| Current trend | `_{TREND_CURRENT_DAYS}d` (default `_30d`) | `now - 30 days` to `now` |
| Previous trend | `_previous_{TREND_BASELINE_DAYS}d` (default `_previous_30d`) | 30 days before the current trend window |

Core metrics per window:

| Metric | Value | Status |
| --- | --- | --- |
| `evidence_volume{window}` | Count of linked problem evidence in the window | `OK`, `PARTIAL`, or `NO_DATA` |
| `distinct_customers{window}` | Distinct non-null customer refs in the window | Window status, or `INSUFFICIENT_DATA` if no customer refs |
| `negative_share{window}` | `(negative + mixed) / total` | Window status, or `INSUFFICIENT_DATA` if the denominator is zero |
| `repeat_complaint_count{window}` | Sum of repeat-link counts for linked feedback IDs | Window status, or `INSUFFICIENT_DATA` if repeat-link input is unavailable |
| `source_diversity{window}` | Count of distinct source types | Window status |

Canonical names such as `evidence_volume`, `distinct_customers`, `negative_share`,
`repeat_complaint_count` and `source_diversity` are aliases of the configured
measurement window. Their metadata includes `alias_of` and the aliased metric name.

Growth metrics:

| Metric | Formula |
| --- | --- |
| `volume_growth_abs` | `current_30d_volume - previous_30d_volume` |
| `volume_growth_pct` | `(current - previous) / previous`, or `INSUFFICIENT_DATA` when previous is zero |
| `customer_growth_abs` | `current_30d_customers - previous_30d_customers` |
| `customer_growth_pct` | `(current - previous) / previous`, or `INSUFFICIENT_DATA` when previous is zero |
| `negative_share_change` | `current_30d_negative_share - previous_30d_negative_share` |
| `assessment_velocity_delta` | Alias of `volume_growth_abs` retained for compatibility |

Growth status rules:

- `NO_DATA` when neither trend window has source coverage.
- `INSUFFICIENT_DATA` when either trend window lacks full coverage, or a
  percentage denominator is zero.
- `OK` only when both windows have full coverage and usable values.

Window coverage is calculated from the observed date range of the problem's
linked evidence:

- `full`: the window starts on or after the first observed date.
- `partial`: the dataset starts inside the window.
- `outside` / `no data`: the window does not overlap the dataset dates.

An uncovered window returns `NO_DATA` with `metric_value = null`, not zero. A
covered window with no matching records returns `OK` with zero. This distinguishes
"we observed zero" from "we have no coverage".

For a problem with zero evidence, all core metrics are emitted with `NO_DATA`;
the lifetime evidence volume is also `NO_DATA`.

Daily rows are inserted for each problem/day:

```text
feedback_count
negative_count
```

`negative_count` is counted once per feedback/day when any linked insight for that feedback is negative or mixed.

### 7.3 Persistence and UI reading

`problem_measurement_snapshots` stores every windowed metric. The canonical names
are therefore directly comparable with older rows, while the suffixed names make
the window explicit without requiring metadata interpretation.

The UI shows a curated set of primary metrics, plus a collapsible table containing
all remaining window variants. Status and coverage are displayed without treating
missing coverage as zero.

---

## 8. Prioritisation engine

Implemented in `backend/app/intelligence/prioritization.py`.

### 8.1 Weights

Configured weights:

```text
customer_impact       0.30
business_risk         0.30
operational_impact    0.15
trend                 0.15
strategic             0.10
```

They are normalized by their sum before scoring. With defaults the sum is 1.0.

### 8.2 Component formulas

`log_scale(value, cap) = clamp(log1p(value) / log1p(cap), 0, 1)`

Inputs are read from the stored measurement snapshots, not recomputed from all
linked evidence:

```text
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

Missing metric values contribute zero to their component and are listed in
`missing_metrics`. Their measurement status is also recorded in
`supporting_evidence.measurement_status`. `data_completeness` records the fraction
of components with at least one usable input. A missing trend value no longer
silently becomes the neutral `0.5`.

Risk terms and weights:

```text
unauthorized 1.0, fraud 1.0, money deducted 1.0, debited 0.9,
security 0.9, locked 0.7, blocked 0.7, kyc 0.7,
regulatory 0.8, duplicate payment 0.8,
payment failed 0.7, failed transfer 0.7
```

Risk terms are searched in the concatenation of reported problems, reported symptoms and redacted feedback text. Each term contributes once if present.

The risk score is an **indicator score, not a verified incident score**. Every
priority snapshot carries:

```text
supporting_evidence.risk_indicators = [{term, weight}, ...]
supporting_evidence.risk_indicator_score = business_risk
supporting_evidence.verified_risk.status = "NOT_VERIFIED"
supporting_evidence.verified_risk.verified_by = null
supporting_evidence.verified_risk.source = null
```

No verification is inferred from text. A future verified-risk source must set the
verification fields explicitly.

Module strategic weights:

```text
payments 0.95, authentication 0.90, accounts 0.85, onboarding 0.85,
cards 0.80, loans 0.80, deposits 0.70, support 0.70,
notifications 0.60, navigation 0.55
```

### 8.3 Priority score and escalation

```text
priority_score =
      0.30 * customer_impact
    + 0.30 * business_risk
    + 0.15 * operational_impact
    + 0.15 * trend
    + 0.10 * strategic
```

Escalation:

- `ESCALATE` if `business_risk >= PRIORITY_ESCALATION_RISK_THRESHOLD` (0.75).
- `ESCALATE` if `trend >= 0.8` and `customer_impact >= 0.5`.
- Otherwise `WATCH` if `priority_score >= 0.6`.
- Otherwise `NORMAL`.

Ranking is by priority score descending, then evidence count descending, then data
completeness descending.

Missing inputs are recorded in `missing_metrics` and are not silently presented as
observed data. Their contribution is zero, and `data_completeness` shows how much
of the score is supported by available measurement inputs.

Priority snapshots persist the measurement window start/end used for the score,
so the score's provenance is inspectable.

---

## 9. Backlog normalisation and validation (Modules F-G)

Implemented in `backend/app/services/backlog.py` and `backend/app/intelligence/retrieval.py`.

### 9.1 Upload parsing and normalisation

- Required columns: `backlog_id`, `title`, `description`.
- Maximum 1000 rows.
- Duplicate backlog IDs are row errors.
- Missing title/description are row errors.
- Cells starting with `=`, `+`, `-`, `@`, tab or CR trigger a formula-injection warning and are neutralised on export.
- Acceptance criteria are split on `|` and newlines, then on `;`.
- Upload status is `validated` if there are no row errors, otherwise `validated_with_errors`.

### 9.2 Backlog profiling

Backlog text is built from title, description, acceptance criteria, product area and optional structured fields.

- Intent/aspect/symptom keys come from the same regex lexicon as the feedback pipeline.
- Journey node resolution order:
  1. `product_area` alias map.
  2. First aspect `node_id` present in the taxonomy.
  3. `best_node(text, threshold=2.0)`.
- Token set is used later for Jaccard similarity.

### 9.3 Hybrid retrieval

`HybridRetriever` is fitted on canonical problem texts (`title + problem_statement`).

For each backlog item:

- Dense score = cosine similarity between backlog embedding and problem embeddings.
- Sparse score = cosine similarity between backlog TF-IDF vector and problem TF-IDF matrix.
- Dense and sparse matrices are row-normalized by their row maximum.
- Combined score:

```text
combined = RETRIEVAL_DENSE_WEIGHT * dense_normalized
         + RETRIEVAL_SPARSE_WEIGHT * sparse_normalized
```

Defaults are 0.6 dense and 0.4 sparse.

If a cross-encoder reranker is configured and installed, the top 8 candidates are blended as:

```text
0.6 * cross_encoder_score + 0.4 * hybrid_score
```

Otherwise the deterministic hybrid score is used.

Retrieval only selects candidates. It is not the final relationship decision.

### 9.4 Alignment features

For each candidate problem:

- `similarity` = hybrid retrieval score.
- `lexical` = Jaccard overlap between backlog tokens and `title + statement` tokens.
- `node_alignment`:
  - 1.0 if the problem node is exactly one of the backlog's nodes.
  - 0.6 if both fall under the same taxonomy module.
  - 0.0 otherwise.
- `intent_alignment`:
  - 1.0 if problem intent is in backlog intents.
  - 0.8 if the problem aspect matches a backlog aspect.
  - 0.7 if a backlog intent's `node_hint` equals the problem aspect node.
  - 0.0 otherwise.
- `coverage` = covered problem symptoms / detected problem symptoms.
  - Covered means at least one coverage term for the symptom appears in the backlog description or acceptance criteria.
  - If no symptom is detected, coverage is token Jaccard against the problem title.

### 9.5 Alignment score

```text
alignment_score =
      0.35 * max(similarity, lexical)
    + 0.25 * node_alignment
    + 0.20 * intent_alignment
    + 0.20 * coverage
```

The score is rounded to 3 decimals.

### 9.6 Relationship decision tree

`signal = max(similarity, lexical)`

```text
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

- `ADDRESSES` or `PARTIALLY_ADDRESSES` with fewer than 2 supporting feedback mentions becomes `NEEDS_REVIEW` with an uncertainty note.
- `ADDRESSES` with coverage in `[0.25, 0.45)` becomes `NEEDS_REVIEW`.

A candidate is dropped when it is `NO_CLEAR_RELATIONSHIP` and both `similarity < 0.18` and `node_alignment == 0`.

### 9.7 Overall alignment for a backlog item

Findings are ranked by relationship priority:

```text
ADDRESSES 5
PARTIALLY_ADDRESSES 4
NEEDS_REVIEW 3
RELATED_BUT_NOT_SOLVING 2
NO_CLEAR_RELATIONSHIP 1
CONTRADICTS_OR_OUT_OF_SCOPE 0
```

Verdict:

| Verdict | Condition |
| --- | --- |
| `strong` | Best `ADDRESSES` has score >= 0.55 and >= 2 supporting mentions |
| `needs_review` | Any `ADDRESSES` below those gates, or any `NEEDS_REVIEW` |
| `partial` | Any `PARTIALLY_ADDRESSES` |
| `weak` | Only `RELATED_BUT_NOT_SOLVING` / lower |
| `unsupported` | No findings or only no-relationship |

### 9.8 AC coverage, gaps and uncovered problems

Per backlog item:

```text
ac_coverage = mean(finding.ac_coverage for all findings)
```

This is the average **symptom coverage** across matched problem findings. It is displayed as "AC coverage" in the UI, but it is not a literal percentage of acceptance criteria that are satisfied. A finding contributes an AC gap when a problem symptom has no matching coverage term in the backlog description/criteria.

`uncovered_high_evidence_problems`:

- Problem not addressed by any `ADDRESSES` or `PARTIALLY_ADDRESSES` finding.
- `evidence_count >= 5`.
- Sorted by the problem query order (evidence count descending).
- Capped at 12 entries.

The report summary field `high_evidence_uncovered_problems` is the length of this capped list, not necessarily the total number of all high-evidence gaps.

### 9.9 Report limitations

The generated report records:

- Alignment is derived only from supplied feedback and backlog text.
- Organisational priority is not calculated; source priority is preserved as metadata.
- `NEEDS_REVIEW` must be resolved by a product owner.
- Similarity is used for candidate retrieval, never as the final relationship decision.

---

## 10. UI calculations, page by page

The frontend uses `frontend/src/lib/api.ts` with API base `/api/v1`.

### 10.1 Shared formatting

`frontend/src/lib/format.ts`:

| Function | Output |
| --- | --- |
| `number(value)` | `Intl.NumberFormat("en-US")`; null/undefined/NaN -> `-` |
| `percent(value)` | `Math.round(value * 100)%`; null/undefined/NaN -> `-` |
| `date(value)` | `en-GB`, `DD Mon YYYY`; missing -> `-` |
| `dateTime(value)` | `en-GB`, `DD Mon YYYY, HH:mm`; missing -> `-` |
| `label(value)` | Replaces `_`/`-` with spaces and title-cases words |
| `truncate(value, length)` | Truncates with `...` |

Scores shown with inline `Math.round(value * 100)` are percentages of a 0-1 stored score.

### 10.2 Layout and navigation

`frontend/src/components/Layout.tsx` calls `GET /meta/source`.

Displayed values:

- Provider: `meta.provider`, fallback `rules-v1`.
- Taxonomy version: `meta.taxonomy_version`, UI prefixes `v`.
- Schema version: `meta.schema_version`.
- Storage is hard-coded as `local://`.
- Top-right version pill: `meta.code_version`.
- "Analytics ready" when `meta.latest_completed_run` exists; otherwise "Pipeline starting".
- Synthetic warning: `meta.synthetic_warning`, with a fallback sentence.
- Navigation links are static: Journey explorer, Customer problems, Theme map, Backlog validation.

### 10.3 Journey explorer (`/` and `/journey`)

Data source: `GET /journey`.

Response:

```text
version, run_id, tree, unmapped
```

Each tree node has:

```text
node_id, parent_id, node_type, display_name, description,
problem_count, evidence_count, children
```

Calculation in `routes.py::journey_explorer`:

1. Read `customer_problems` grouped by `journey_node_id`.
2. `direct_counts[node] = number of problems` assigned directly to that node.
3. `direct_evidence[node] = sum(problem.evidence_count)` for that node.
4. Recurse over taxonomy children and add child totals:

```text
node.problem_count  = direct_problems(node) + sum(child.problem_count)
node.evidence_count = direct_evidence(node) + sum(child.evidence_count)
```

Therefore a parent node shows its own mapped problems plus all descendant feature problems.

UI calculations:

- Module cards: only `node_type === "module"` from the flattened tree.
- Card problem count: `node.problem_count`.
- Card evidence count: `node.evidence_count`.
- Tree columns: same fields.
- Relative evidence bar:
  - `maxEvidence = max(1, max evidence_count across flattened tree)`.
  - Width = `max(2, evidence_count / maxEvidence * 100)%` when data exists.
  - A zero-evidence node still renders a small 2% bar because of the minimum width.
- Version badge: `Taxonomy v{version}`.
- Clicking a node navigates to `/problems?journey={node_id}`.

The response also includes `unmapped`, but the active Journey page no longer displays an unmapped card.

### 10.4 Customer problems (`/problems`)

Data source: `GET /problems` with query parameters:

```text
run_id?, search?, journey?, status?, sort=evidence|recent|negative|title,
page=1, page_size=20
```

If `run_id` is omitted, the backend uses the latest completed feedback run (`repository.resolve_run_id`).

Backend filtering and ordering:

- Search matches title or problem statement with `LIKE`.
- Journey filter matches the exact node or any descendant (`node_id LIKE 'node.%'`).
- Lifecycle status matches exactly.
- Sort:
  - `evidence`: `evidence_count DESC, last_seen DESC`
  - `recent`: `last_seen DESC, evidence_count DESC`
  - `negative`: `negative_count DESC, evidence_count DESC`
  - `title`: title ascending
- Pagination is 20 rows per page by default.
- `total` is a SQL count of matching problems.
- `journey_name` is looked up from `taxonomy_nodes`.

UI calculations:

- `totalPages = max(1, ceil(total / page_size))`.
- Search input is debounced by 320 ms; changing search resets page.
- Journey dropdown options come from `GET /feedback/options`, filtered to `node_type === "module"`.
- Table values:
  - Problem title + `problem_id`.
  - Journey: `journey_name || journey_node_id || "UNMAPPED"`.
  - Symptom: `label(symptom_category)`.
  - Evidence: `evidence_count`.
  - Customers: `distinct_customers`.
  - Status: lifecycle status badge; green only when `accepted`.
  - Latest: `date(last_seen)`.
- Footer warning is static: customer evidence alignment is not organisational priority.

### 10.5 Problem detail (`/problems/:problemId`)

Data sources:

```text
GET /problems/{problem_id}
GET /problems/{problem_id}/measurement
GET /problems/{problem_id}/priority
```

#### Problem payload

`repository.get_problem` returns:

- All `customer_problems` columns.
- `mappings`: joined to taxonomy display name/description, ordered by mapping type and confidence descending.
- `evidence`: up to 100 rows, newest first.
- `insights`: up to 200 rows for feedback IDs linked to this problem, ordered by confidence descending.
- Each insight is attached to evidence with the same `feedback_id`.
- `reviews`: problem review decisions, newest first.

Because insights are selected by `feedback_id`, an evidence item can display multiple insight records extracted from that feedback item.

#### Header and stat cards

| UI value | Source |
| --- | --- |
| Eyebrow | `problem_id · cluster_id` (or `cluster`) |
| Title | `title` |
| Subtitle | `problem_statement` |
| Lifecycle badge | `lifecycle_status` |
| Evidence-link badge | `evidence_count` |
| Distinct customers | `distinct_customers` |
| Negative evidence | `negative_count`; explicitly labelled "Not a severity score" |
| First seen | `date(first_seen)` |
| Latest | `date(last_seen)` |
| Journey | `journey_name || journey_node_id || "UNMAPPED"` |
| Taxonomy version | `taxonomy_version` |

#### Impact measurement card

`GET /measurement` returns snapshots from the latest measurement run for the
problem. The UI displays a curated set of primary metrics and puts the remaining
window variants in an expandable table.

If no snapshots exist, the UI creates three derived metrics from the problem row:

| Derived metric | Value | Status |
| --- | --- | --- |
| `evidence_volume` | `evidence_count` | `DERIVED` |
| `distinct_customers` | `distinct_customers` | `DERIVED` |
| `negative_share` | `negative_count / evidence_count` (null if zero) | `DERIVED` |

Metric formatting:

- Null/undefined value -> `NO_DATA`.
- `unit === "ratio"` -> `Math.round(value * 100)%`.
- Growth records (`volume_growth_abs`, `customer_growth_abs`, `assessment_velocity_delta`) -> signed number.
- Growth ratios and `negative_share_change` -> percentage or percentage points.
- Otherwise -> formatted number plus unit.
- Window text uses `date(window_start)` to `date(window_end)`, or "Directly derived from linked evidence" for derived metrics.
- Coverage text uses `metadata.window_coverage`.
- Status badge is green for `OK`, blue for `DERIVED`, amber otherwise.
- Remaining window variants are shown in an expandable "All measurement windows" table.

#### Priority card

Data source: latest priority snapshot for that problem (`ORDER BY calculated_at DESC LIMIT 1`).

| UI value | Calculation |
| --- | --- |
| Escalation badge | `escalation_status` |
| Priority score | `Math.round(priority_score * 100) / 100` |
| Rank | `#rank` |
| Component bar width | `Math.round(component_score * 100)%` |
| Component label | fixed mapping from the five score fields |
| Risk indicators | `supporting_evidence.risk_indicators[].term` |
| Verified risk | `supporting_evidence.verified_risk.status` |
| Data completeness | `supporting_evidence.data_completeness` |

The UI labels business risk as a risk indicator and shows `NOT_VERIFIED` until a
verification source exists. It does not display `escalation_reasons` or
`missing_metrics`, although those fields are returned by the API.

If no priority row exists yet, the UI shows "Priority snapshot not calculated" and suggests re-running the pipeline.

#### Evidence details

Each evidence item shows:

- Feedback ID.
- Source type and platform.
- Rating, if present.
- Submitted date.
- Evidence span.
- Linked insight records.

For each insight, the UI shows:

- Intent: `intents` if non-empty, otherwise the singular `customer_intent`.
- Aspect: `aspects` if non-empty, otherwise the singular `aspect`.
- Symptom: `reported_symptom`.
- Emotion, customer effort, outcome.
- Language, fallback `unknown`.
- Technical root cause, fallback `unknown`.
- Extracted problem: `reported_problem`.
- Confidence: `Math.round(confidence * 100)%`.
- Field confidence: each value rounded to a percentage.

Per-evidence evidence and insight lists are capped by the API at 100 evidence rows and 200 insight rows.

#### Mapping and reviews

- The "Underlying problem and mapping" block uses the first mapping from `data.mappings[0]` as primary.
- Journey mapping card lists all mappings with `display_name || node_id`, confidence percentage, rationale, type and status.
- Review form posts to `POST /problems/{id}/review` and then reloads the problem.
- Review history is rendered from `reviews`, newest first.

### 10.6 Backlog validation (`/backlog`)

Data sources:

```text
GET /backlog-uploads
GET /backlog-uploads/{upload_id}
POST /backlog-uploads/{upload_id}/validate
GET /backlog-validation-runs/{run_id}
```

UI behaviour:

1. Load upload list and auto-select the first upload.
2. Show the upload detail.
3. "Validate against customer problems" posts `{force_rerun: true}` with an idempotency key.
4. Poll the validation run every 1500 ms while status is `queued` or `running`.
5. When status is `completed` and `report_id` exists, navigate to `/reports/{report_id}`.

Displayed values:

| UI value | Source |
| --- | --- |
| Filename | `upload.filename` |
| Object hint | `source_uri` and first 16 chars of `generation` |
| Valid rows | `valid_rows` |
| Invalid rows | `invalid_rows` |
| Status badge | `upload.status`; green only for `validated` |
| Generation | first 14 chars of `generation` |
| Row errors | `errors[]` with row number, backlog ID and joined error strings |
| Warnings | `warnings[]` |
| Backlog table | `items[]`: ID, title/description, product area, priority, acceptance criteria |

The live progress bar is UI-only:

- 100% when the validation run is `completed`.
- 55% otherwise.

It is not a measurement of actual stage progress.

The page does not upload new files; uploads are API-driven.

### 10.7 Validation report (`/reports/:reportId`)

Data source: `GET /backlog-validation-reports/{report_id}`.

The response wraps `report`, outer `summary`, `reviews`, `reviewer_status`, `filename`, `upload_id`.

The page reads `data.report.summary` into a local `summary` variable.

#### Stat cards

| UI value | Source/calculation |
| --- | --- |
| Backlog items | `summary.backlog_count` |
| Canonical problems compared | `summary.canonical_problem_count` |
| Findings | `summary.findings` |
| High-evidence uncovered | `summary.high_evidence_uncovered_problems` |
| Evidence run | first 18 chars of `report.feedback_run_id` |
| Taxonomy version | `report.versions.taxonomy` |

#### Relationship distribution

Source: `summary.relationships` (counts of findings by relationship).

- Rows are sorted by count descending.
- Bar width = `value / max(1, totalFindings) * 100%`.
- `totalFindings = Number(summary.findings)`.

#### Alignment by backlog item

Source: `summary.alignment` (counts of backlog items by overall alignment).

- Displayed categories: strong, partial, weak, unsupported, needs_review.
- Missing categories default to 0.
- Bar width = `count / max(1, summary.backlog_count) * 100%`.

#### Version row

Only scalar values from `report.versions` are displayed. Nested objects are filtered out. This filtering was added to prevent the report page from crashing on a nested `retrieval` object.

#### Backlog item findings

For each item:

- Header: backlog ID, title, overall alignment badge.
- Meta: journey name, `Math.round(ac_coverage * 100)% AC coverage`, number of findings, source priority or "No source priority".
- Items with `overall_alignment !== "unsupported"` are expanded by default.
- Business goal is hidden when it equals `NOT_PROVIDED`.
- Findings are sorted by alignment score and supporting feedback count from the backend.
- Finding score = `Math.round(alignment_score * 100)%`.
- Each finding shows rationale, optional uncertainty, up to 3 evidence spans, and acceptance-criteria gap messages.
- Evidence rows show feedback ID, source type, date and rating if present.

Remember: displayed "AC coverage" is mean symptom coverage, not literal acceptance-criteria completion.

#### High-evidence uncovered problems

- Source: `report.uncovered_high_evidence_problems`.
- Displays title, journey name or "Unmapped", evidence count, and "mentions".
- Links to the problem detail page.
- The list is capped at 12 by the backend.

#### Product-owner review

- Form posts to `POST /backlog-validation-reports/{report_id}/review`.
- Reviewer, decision and note are stored.
- Existing reviews are rendered newest first from `data.reviews`.
- The report is never auto-approved or auto-rejected.

#### Limitations

Rendered verbatim from `report.limitations`.

### 10.8 Theme map (`/themes`)

Data source: `GET /problem-map` (optionally `?run_id=`). `POST /problem-map/recompute` rebuilds the snapshot; `GET /problem-map/{problem_id}` returns one theme with its full problem detail.

The map is computed by `mds_engine` and described in `docs/pipeline-algorithms.md` section 12.3. The UI never treats coordinates as business meaning.

Displayed values:

- Bubble `x`/`y`: `display_x`/`display_y` from the persisted MDS snapshot. Axes are hidden because they have arbitrary orientation.
- Bubble radius: `9 + 24 * sqrt(evidence_volume / max_evidence_volume)`, with a minimum volume denominator of 1.
- Bubble label: evidence volume, capped at `99+`.
- Bubble fill:
  - `negative_share` mode: HSL interpolation from teal (`0`) to red (`1`);
  - `priority_score` mode: blue (`0`) to red (`1`);
  - `business_risk_score` mode: teal (`0`) to red (`1`);
  - missing value: neutral grey.
- Bubble outline: growth colour from `volume_growth_pct` (red >= 25%, amber > 0, teal <= -25%, otherwise slate). Dashed outline when `coverage_status` is `uncovered` or `needs_review`.
- Stat cards: theme count, raw MDS stress, uncovered themes, and count of `ESCALATE` themes.
- Selected-theme panel: evidence, distinct customers, negative share, volume growth, priority score/rank, five priority components, top neighbours by cosine similarity, and links to the problem and latest validation report.
- Watchlist: themes with `ESCALATE`, `uncovered`, or `needs_review`, sorted by `priority_score` descending and capped at 8.

`negative_share` is labelled as negative evidence share, not a severity score. Backlog coverage is joined from the latest validation report whose `feedback_run_id` matches the feedback run; if no report exists, coverage is `unknown`.

---

## 11. What is intentionally not shown or not active

- **Overview and Pipeline runs pages**: files remain under `frontend/src/pages/`, but routes and sidebar links were removed.
- **Data quality UI**: `GET /data-quality` exists, but no active page displays it.
- **Duplicate UI**: `GET /duplicates` exists, but no active page displays it.
- **Problem relationships UI**: `GET /problem-relationships` exists, but no active page displays it.
- **Priority list UI**: `GET /priorities` exists, but only per-problem priority is shown.
- **Taxonomy proposals UI**: API exists, but the active Journey page does not show proposals.
- **Upload UI**: backlog uploads are created through the API, not from the active page.
- **Unmapped Journey card**: the API still returns `unmapped`, but the active page does not render it.
- **Survival analysis and conjoint analysis**: guarded/disabled; no active UI consumes them.
- **MDS theme map**: active on `/themes`; positions are semantic only and are never used as severity or priority.
- **HDBSCAN**: `clustering_provider` exists in settings, but the running discovery path is signature grouping + Union-Find; HDBSCAN is not implemented.
- **Taxonomy cross-encoder**: `TAXONOMY_CROSS_ENCODER_ENABLED` exists but is not used by the mapping path.
- **Cross-encoder reranker for backlog**: optional and only active when configured and installed; default is `none`.
- **Root cause**: extraction always stores `technical_root_cause="unknown"` unless an LLM provider explicitly returns something that passes conversion; no root cause is inferred by the rules path.
- **Churn/severity**: negative sentiment is not a churn prediction or a severity score.
- **Report live progress**: the backlog validation progress bar is a UI placeholder, not stage-level progress.

---

## 12. Default parameters that affect displayed values

| Setting | Default | Effect |
| --- | --- | --- |
| `PIPELINE_MAX_ROWS` | 25000 | Feedback rows processed |
| `MAX_FEEDBACK_BYTES` | 25 MB | Source size guard |
| `NEAR_DUPLICATE_THRESHOLD` | 0.85 | Near-duplicate Jaccard gate |
| `NEAR_DUPLICATE_MIN_TOKENS` | 5 | Minimum tokens for near-duplicate candidates |
| `REPEAT_COMPLAINT_WINDOW_DAYS` | 30 | Repeat complaint window |
| `DATA_QUALITY_MIN_CHARS` | 3 | Quality warning threshold |
| `DATA_QUALITY_MAX_CHARS` | 5000 | Quality warning threshold |
| `EMBEDDING_DIMENSIONS` | 96 | Local SVD dimensions |
| `CLUSTERING_SIMILARITY_THRESHOLD` | 0.64 | Group merge base; effective merge 0.82 |
| `TAXONOMY_SEMANTIC_THRESHOLD` | 0.45 | Semantic fallback gate |
| `TAXONOMY_ACCEPT_THRESHOLD` | 0.55 | Mapping acceptance gate |
| `TAXONOMY_OPEN_SET_THRESHOLD` | 0.35 | Proposal reason boundary |
| `MEASUREMENT_WINDOW_DAYS` | 90 | Main measurement window metadata |
| `TREND_BASELINE_DAYS` | 30 | Trend baseline window |
| `TREND_CURRENT_DAYS` | 30 | Trend current window |
| `PRIORITY_*_WEIGHT` | 0.30/0.30/0.15/0.15/0.10 | Priority component weights |
| `PRIORITY_ESCALATION_RISK_THRESHOLD` | 0.75 | Business-risk escalation gate |
| `MDS_RANDOM_STATE` | 42 | Reproducible MDS initialisation |
| `MDS_MAX_ITER` | 300 | MDS SMACOF iteration cap |
| `MDS_NEIGHBORS` | 5 | Similar themes stored per theme |
| `MDS_MIN_THEMES` | 2 | Minimum themes for a map |
| `MDS_MAX_THEMES` | 500 | Highest-evidence themes mapped per run |
| `MDS_COORDINATE_SCALE` | 1.0 | Display-coordinate scale after centring |
| `RETRIEVAL_DENSE_WEIGHT` | 0.6 | Hybrid retrieval dense weight |
| `RETRIEVAL_SPARSE_WEIGHT` | 0.4 | Hybrid retrieval sparse weight |
| `RETRIEVAL_TOP_K` | 8 | Candidate problems considered per backlog item |
| `EXTRACTION_PROVIDER` | `rules` | Deterministic extraction by default |

---

## 13. Verification quick reference

Backend checks:

```bash
source .venv/bin/activate
ruff check backend tests
python -m pytest -q
```

Frontend build:

```bash
cd frontend
npm run build
```

Useful API checks while the backend is running:

```bash
curl -s http://127.0.0.1:8000/api/v1/meta/source
curl -s http://127.0.0.1:8000/api/v1/journey
curl -s http://127.0.0.1:8000/api/v1/problems?page=1
curl -s http://127.0.0.1:8000/api/v1/problems/CP-a5082b92f9b4c2/measurement
curl -s http://127.0.0.1:8000/api/v1/problems/CP-a5082b92f9b4c2/priority
```

The exact problem IDs depend on the current database and pipeline run.
