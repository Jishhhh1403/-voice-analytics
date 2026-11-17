# Mapping Mechanics and Factor F11 White Space

This document explains how the platform maps:

```text
feedback -> canonical theme -> factor -> backlog item
```

It then explains why factor `F11` (“Account Balance Consistency and Overview Mismatches”) is a special case: it is strongly connected to themes but has no downstream backlog edge at all.

The analysis uses the local database at `data/local/bci.db` and the latest completed runs.

## 1. Executive summary

The mapping is not one fuzzy match. It is a chain of separate evidence products:

1. Feedback records are linked to canonical problems (“themes”) through persisted problem evidence.
2. Canonical problems are linked to FAMD dimensions through factor membership rows.
3. FAMD dimensions are scored and named as factors.
4. Factors are compared with backlog text using hybrid retrieval, lexical overlap and coverage thresholds.
5. Only the strongest factor matches per backlog are persisted as report findings.
6. The mapping graph exposes those persisted links to the `/mappings` page.

For the current data:

- There are 15,000 feedback records, 362 canonical themes and 12 factors.
- The mapping graph has 13,547 feedback-theme links, 2,657 theme-factor links and 40 factor-backlog links.
- `F11` has **200** theme-factor membership links.
- `F11` has **0** factor-backlog links.
- `F11` is rank 10 of 12, so it is not listed in the report’s “high-priority uncovered factors” section, which only includes ranks 1-5.
- `F11` is nevertheless genuine downstream white space in this report: no retained backlog finding mentions it, and its best measured coverage against any backlog is only `0.0654` (`NOT_COVERED`).

In one sentence:

> F11 is not missing customer evidence. It is missing a matching backlog. The report then hides even that fact because F11 is outside the report’s rank-5 high-priority gap filter and outside the per-backlog top-8 retained findings.

## 2. Data snapshot and identifiers

| Item | Value |
|---|---|
| Feedback run | `RUN-20261113044403-8935d1` |
| Canonical themes in feedback run | 362 |
| FAMD dimension run | `DIM-20261113112110-cebf16` |
| Factor prioritisation run | `FPR-20261114070925-e248d5` |
| Factor score model | `factor-evidence-v1` |
| Backlog upload | `UP-f81fb71f0036` (`sample_backlog_upload.csv`) |
| Validation run | `VRUN-d73f9cb4eed0` |
| Validation report | `RPT-abfba1eb8309` |
| F11 narrative serialization | `NAR-20261113182453-d58966` |
| Taxonomy version | `1.0.0` |
| Embedding model | `tfidf-svd-96-v1` |
| Retrieval | hybrid, dense `0.6`, sparse `0.4`, reranked `false` |
| Factor weights | prevalence `0.30`, statistical `0.25`, representation `0.25`, semantic `0.20` |
| Schema version | `1.0.0` |
| Code version | `0.1.0` |

## 3. What the mapping graph is

`MappingGraphService` in `backend/app/services/mappings.py` builds a read-only graph for the `/mappings` page.

It contains four node layers:

| Layer | Source table | Meaning |
|---|---|---|
| Feedback | `feedback_records` | Individual customer feedback records for the selected/latest completed feedback run |
| Themes | `customer_problems` | Canonical problems extracted from feedback |
| Factors | `factor_prioritisation_scores` | Scored and named FAMD factors |
| Backlogs | `validation_reports.report_json.backlog_items` | Backlog items from the latest matching factor-based validation report |

It contains three link types:

| Link | Source | Meaning |
|---|---|---|
| `feedback_theme` | `problem_evidence` | Which feedback supports which canonical theme |
| `theme_factor` | `dimension_problem_membership` | Which themes belong to which FAMD factor |
| `factor_backlog` | report `findings` | Which factors were matched to which backlog items by validation |

The graph is intentionally read-only. It does not create, edit or approve mappings.

Readiness values are `NO_FEEDBACK_RUN`, `NO_THEMES`, `READY` and `PARTIAL`. The current graph is `READY`.

A graph can be `READY` even when a factor has no backlog edge. Readiness only says that the required runs and report exist. It does not say that every factor is covered.

## 4. Stage-by-stage mechanics

### 4.1 Feedback to canonical themes

Feedback is ingested into `feedback_records`. The pipeline extracts problems, stores problem evidence in `problem_evidence`, and clusters/creates canonical problems in `customer_problems`.

For the current feedback run:

- 15,000 feedback records
- 362 canonical themes
- 10,018 feedback records mapped to a primary theme
- 4,982 feedback records unmapped
- 13,547 feedback-theme evidence links

The mapping graph creates a feedback-theme link for every persisted evidence relationship. A feedback record can support more than one theme, so the link count is larger than the mapped feedback count.

Each theme gets:

- `primary_theme_id`: the theme with the strongest evidence weight for that feedback record
- `theme_count`: how many themes that feedback record supports
- `mapped_feedback_count`: how many feedback records support that theme
- `primary_factor_id`: the factor with the highest membership score for that theme

The canonical problem table is the bridge between raw feedback and factors. The graph does not re-run clustering or re-interpret feedback.

### 4.2 Themes to factors

FAMD dimensions are stored in `dimension_analysis_runs`, `dimension_definitions` and `dimension_problem_membership`.

For each canonical problem, `dimension_problem_membership` stores:

- `dimension_id`
- `membership_type` (`high_score`, `associated`, etc.)
- `score`
- `margin`
- `is_ambiguous`

`MappingGraphService` converts each membership row into a `theme_factor` link. It also computes the primary factor per theme from the highest membership score.

Current graph totals:

- 2,657 theme-factor membership links
- 362 themes with a primary factor
- 12 factors

This is important for F11:

- F11 is the factor for dimension `D11`.
- F11 has 200 membership rows: 91 `high_score`, 109 `associated`.
- 100 of those 200 memberships are flagged ambiguous.
- The mapping graph therefore gives F11 200 incoming theme links.

The 200 memberships are not the same as the 20 representative problems shown in the report.

- `factor_prioritisation_scores` uses 200 members as the numerator of prevalence.
- `factor_semantic_assessments.supporting_problem_ids` contains 20 representative problems used for narrative/report evidence.
- All 20 representative problems are members of the 200, but the 180 other members are not listed individually in the report’s F11 evidence block.

### 4.3 Factor scoring

The factor score is:

```text
final_priority_score =
    0.30 * prevalence
  + 0.25 * statistical_importance
  + 0.25 * representation_strength
  + 0.20 * semantic_coherence
```

Definitions:

- Prevalence: `N_f / N * 100`, where `N_f` is the number of canonical problems that are members of the factor.
- Statistical importance: FAMD eigenvalue divided by total inertia, multiplied by 100.
- Representation strength: percentage of canonical problems whose FAMD row contribution reaches at least the expected mean contribution threshold.
- Semantic coherence: mean of the assessable journey/aspect/intent/symptom/banking-process concentration scores.

For F11:

| Component | Raw score | Weight | Weighted contribution |
|---|---:|---:|---:|
| Prevalence | 55.2486 | 0.30 | 16.5746 |
| Statistical importance | 1.4913 | 0.25 | 0.3728 |
| Representation strength | 0.0000 | 0.25 | 0.0000 |
| Semantic coherence | 6.3576 | 0.20 | 1.2715 |
| **Final priority** | **18.2189** |  | **18.2189** |

F11 details:

- 200 of 362 canonical problems are members.
- FAMD eigenvalue is `3.5046` out of total inertia `235.0000`.
- It explains `1.4913%` of FAMD variation.
- `0` of 362 problems meet the representation contribution threshold.
- Semantic coherence is low: journey `1.7246`, aspect `3.7787`, intent `3.2557`, symptom `19.3214`, banking process `3.7074`.
- Score status: `VALIDATED`.
- Eligibility status: `ELIGIBLE`.
- Rank: `10` of `12`.
- Evidence coverage: `100%`.

The high prevalence and low representation/coherence combination matters. F11 touches many problems, but it does not strongly represent individual problems and its member problems are semantically mixed.

### 4.4 Factor naming and the D11 label mismatch

The report and mapping page use the factor name from the narrative serialization:

```text
F11 / D11: Account Balance Consistency and Overview Mismatches
```

The underlying provisional FAMD dimension definition still has:

```text
D11: Beneficiaries · video kyc · cards · controls
```

This is not a display bug in the mapping graph. The graph reads `factor_prioritisation_scores.factor_name`, which is the narrative-approved factor name. The dimension definition is a separate statistical artifact and was not renamed by the factor narrative.

This matters because the narrative name emphasizes balance and account overview, while the D11 statistical label emphasizes beneficiaries, video KYC and card controls. F11’s own description explicitly mixes both:

- positive coefficients: selfie verification clarity and statement generation challenges
- negative coefficients: account balance mismatches and overview discrepancies

The factor’s top feature contributions also mix categories:

- `journey_module=beneficiaries`: `5.1663%`
- `customer_intent=video_kyc`: `3.2203%`
- `journey_feature=cards.controls`: `2.7516%`
- `aspect=balance`: `2.7516%`
- `journey_feature=cards.online`: `2.2319%`

So F11 is not a clean “balance” factor. It is a mixed dimension that the narrative labelled after the dominant negative pattern. That mixed text is later used for backlog retrieval, which helps explain its poor match.

### 4.5 Factors to backlog items

Factor-to-backlog validation is implemented in `BacklogValidationService._validate_factors` in `backend/app/services/backlog.py`.

The process is:

1. Load the latest completed factor prioritisation run.
2. Load each factor’s narrative name, short name, description, business interpretation, journey scope, banking domain, patterns, top features and representative problem IDs.
3. Build a factor text string.
4. Build a backlog text string from title, description, acceptance criteria, product area, intended outcome, customer intent, target feature, target journey and functional scope.
5. Fit a hybrid retriever on the factor texts.
6. Score all factors against all backlog texts.
7. Compute coverage for each factor/backlog pair.

Coverage is:

```text
coverage = 0.5 * semantic_similarity
         + 0.3 * sparse_similarity
         + 0.2 * lexical_jaccard
```

Relationships are:

| Relationship | Rule |
|---|---|
| `COVERS` | `coverage >= 0.45` and (`semantic >= 0.30` or `lexical >= 0.25`) |
| `PARTIALLY_COVERS` | `coverage >= 0.30` |
| `RELATED` | `coverage >= 0.20` |
| `NEEDS_REVIEW` | `coverage >= 0.12` |
| `NOT_COVERED` | `coverage < 0.12` |

Priority-weighted coverage is:

```text
priority_weighted_coverage = coverage * factor_priority_score
```

For each backlog, candidates are sorted by:

1. priority-weighted coverage
2. raw coverage
3. higher-priority factor rank

Only the top **8** candidates per backlog are persisted as findings. Candidates are first dropped if they are `NOT_COVERED` with exactly zero coverage.

Current report consequences:

- 7 backlog items were uploaded.
- 2 are off-domain and unsupported (`BL-2009` greenhouse, `BL-2010` apiary).
- 5 bank-relevant backlogs produced findings.
- 5 backlogs x 8 retained findings = 40 findings.
- The 40 findings contain only 11 distinct problem IDs because each finding is factor-level and reuses the factor’s representative problems.
- Relationship counts across the 40 findings:
  - `COVERS`: 3
  - `PARTIALLY_COVERS`: 3
  - `RELATED`: 9
  - `NOT_COVERED`: 21
  - `NEEDS_REVIEW`: 4

### 4.6 How `factor_coverage` is computed

`factor_coverage` is not computed from all 12 factors x 7 backlogs. It is computed only from the findings that survived the top-8 cut.

For each factor, the service collects matching findings across all backlog summaries:

```text
matches = all retained findings whose factor_id equals this factor
covered_matches = matches with COVERS or PARTIALLY_COVERS
best_match = match with highest coverage, or None
```

Then it stores:

- `covered_by_count`
- `covered_by_backlog_ids`
- `best_coverage`
- `best_embedding_distance`
- `best_relationship`

If a factor has no retained finding, the service writes:

- `best_coverage = 0.0`
- `best_embedding_distance = None`
- `best_relationship = None`

That `0.0` is a default, not a measured similarity. This is exactly what happens to F11.

### 4.7 How the report surfaces gaps

The report’s `uncovered_high_priority_factors` list is not “all factors with zero covered backlogs.”

Its filter is:

```text
priority_rank <= 5 AND covered_by_count == 0
```

Current result:

- `F3` rank 2, best relationship `RELATED`, best retained coverage `0.2629`
- `F4` rank 5, best relationship `RELATED`, best retained coverage `0.2403`

F11 is not in that list because its rank is 10, even though its `covered_by_count` is also 0.

This is a reporting-priority decision, not evidence that F11 is covered.

### 4.8 Report to mapping graph

`MappingGraphService` reads `report.findings`, not `report.factor_coverage`, when building `factor_backlog` links.

Therefore:

- A factor with no retained finding has no graph edge to any backlog.
- F11 has no retained finding.
- F11 has zero `factor_backlog` links in the graph.
- F11 still has 200 `theme_factor` links.

The graph is therefore correct: it shows F11 connected to the theme layer and disconnected from the backlog layer.

Current graph totals:

| Link type | Count |
|---|---:|
| `feedback_theme` | 13,547 |
| `theme_factor` | 2,657 |
| `factor_backlog` | 40 |
| F11 `theme_factor` links | 200 |
| F11 `factor_backlog` links | 0 |

## 5. F11 in detail

### 5.1 Identity

| Field | Value |
|---|---|
| Factor | `F11` |
| Dimension | `D11` |
| Factor name | Account Balance Consistency and Overview Mismatches |
| Short name | Account Balance Consistency |
| Priority rank | 10 of 12 |
| Priority score | 18.2189 |
| Score status | VALIDATED |
| Eligibility | ELIGIBLE |
| Evidence coverage | 100% |
| FAMD membership count | 200 |
| Representative/supporting problems in report | 20 |
| Narrative confidence | 0.95 |
| Narrative model | `gemini-3.5-flash-lite` |
| Narrative prompt | `dimension-factor-narrative-1.1.0` |

### 5.2 Factor evidence profile

The 20 representative problems contain 995 total evidence mentions. The sum of their per-problem distinct-customer counts is 903; this is a sum, not a de-duplicated customer count.

Journey distribution:

| Journey | Problems |
|---|---:|
| Balance enquiry | 6 |
| Selfie verification | 4 |
| Account overview | 4 |
| Transaction history | 4 |
| Account details | 1 |
| Statement generation | 1 |

The largest representative problems are:

| Problem ID | Journey | Problem | Evidence | Distinct customers |
|---|---|---|---:|---:|
| `CP-fe19497c091235` | Transaction history | transaction history: information is missing | 178 | 156 |
| `CP-03bee6d4f7d20e` | Balance enquiry | balance: view balance | 115 | 100 |
| `CP-0779f34a752cba` | Selfie verification | selfie verification: selfie verification | 112 | 102 |
| `CP-a27bb1da306939` | Account overview | account overview: information is missing | 108 | 93 |
| `CP-74fc292dbcf3a7` | Transaction history | transaction history: duplicate payment or debit | 60 | 53 |
| `CP-ba68937bfa286e` | Balance enquiry | balance: screen keeps loading | 53 | 49 |
| `CP-e77abddd30efed` | Account details | Customer experience: information is missing | 53 | 49 |
| `CP-647725675884ec` | Balance enquiry | balance: information does not match | 51 | 48 |
| `CP-663fbb3cfb57aa` | Selfie verification | selfie verification: status or next step is unclear | 50 | 48 |
| `CP-f382a3e2b82e87` | Balance enquiry | balance: feature is inaccessible | 46 | 44 |
| `CP-0e516c3884938e` | Statement generation | statement generation: generate statement | 40 | 39 |
| `CP-adc7fe651bc6e1` | Account overview | account overview: information does not match | 38 | 37 |
| `CP-d39bfe29a346e9` | Balance enquiry | balance: money or response is delayed | 22 | 20 |
| `CP-0aa6ff59b79fdd` | Transaction history | transaction history: money or response is delayed | 21 | 20 |
| `CP-1f5c92b16fa5ab` | Selfie verification | selfie verification: money or response is delayed | 17 | 16 |
| `CP-6dc0349c2fc0a0` | Account overview | account overview: money or response is delayed | 16 | 14 |
| `CP-5a9402f44dc81b` | Balance enquiry | balance: app returns an error | 5 | 5 |
| `CP-6eefecad0a66f8` | Account overview | account overview: app returns an error | 4 | 4 |
| `CP-ca083d15a674b6` | Transaction history | transaction history: app returns an error | 4 | 4 |
| `CP-316162b13dc5df` | Selfie verification | selfie verification: app returns an error | 2 | 2 |

This profile is already a warning sign. The factor contains a strong balance/overview/transaction-history cluster and a separate selfie-verification cluster. The narrative name follows the balance cluster, but the representative set still includes selfie verification and statement generation.

### 5.3 What the report says about F11

In `RPT-abfba1eb8309`, F11 has:

```text
covered_by_count: 0
covered_by_backlog_ids: []
best_coverage: 0.0
best_embedding_distance: null
best_relationship: null
```

Read this carefully:

- It does not say “F11 was compared and scored exactly 0.0.”
- It says “F11 had no retained finding, so there is no best match.”
- The 0.0 is the service’s default when `best_match` is `None`.
- The null embedding distance confirms that no match was retained.

F11 is also absent from:

- `findings`
- `backlog_items[*].findings`
- `backlog_coverage_matrix`
- `validation_findings`
- the mapping graph’s `factor_backlog` links

### 5.4 What F11 actually scores against each backlog

The stored report only contains the top 8 findings per backlog. To understand F11’s true position, the factor/backlog scoring was reproduced with the same `HybridRetriever`, factor text and backlog text used by `BacklogValidationService`.

The reproduction was checked against stored findings:

- `BL-2001` / `F7` reproduced `0.7029` / `COVERS`
- `BL-2003` / `F1` reproduced `0.6452` / `COVERS`
- `BL-2004` / `F12` reproduced `0.6011` / `COVERS`
- `BL-2006` / `F1` reproduced `0.4057` / `PARTIALLY_COVERS`
- `BL-2007` / `F12` reproduced `0.3717` / `PARTIALLY_COVERS`

F11 vs all 7 backlogs:

| Backlog | Semantic | Sparse | Lexical | Coverage | Relationship | Priority-weighted | Rank |
|---|---:|---:|---:|---:|---|---:|---|
| `BL-2001` | 0.0356 | 0.0261 | 0.0531 | 0.0362 | `NOT_COVERED` | 0.6595 | 9/12 |
| `BL-2003` | 0.0856 | 0.0404 | 0.0526 | 0.0654 | `NOT_COVERED` | 1.1915 | 9/12 |
| `BL-2004` | 0.0413 | 0.0148 | 0.0259 | 0.0302 | `NOT_COVERED` | 0.5502 | 11/12 |
| `BL-2006` | 0.0000 | 0.0000 | 0.0000 | 0.0000 | `NOT_COVERED` | 0.0000 | not retained |
| `BL-2007` | 0.0056 | 0.0000 | 0.0000 | 0.0028 | `NOT_COVERED` | 0.0510 | 12/12 |
| `BL-2009` | 0.0000 | 0.0000 | 0.0000 | 0.0000 | `NOT_COVERED` | 0.0000 | no candidates |
| `BL-2010` | 0.0000 | 0.0000 | 0.0000 | 0.0000 | `NOT_COVERED` | 0.0000 | no candidates |

Interpretation:

- F11’s best measured coverage is only `0.0654` against `BL-2003`.
- That is below the `NEEDS_REVIEW` threshold of `0.12`.
- It is far below `RELATED` at `0.20`.
- Even without the top-8 cut, F11 would be `NOT_COVERED` against every backlog in this upload.
- The top-8 cut does not create the coverage gap. It hides the detailed negative result and turns it into “no finding.”

The cut still matters for auditability. F11 ranks 9th for `BL-2001` and `BL-2003`, so it narrowly misses retention. A reader of the report sees `0.0` and `null`, not the actual `0.0362` or `0.0654` score.

### 5.5 Why F11 is white space

F11 is white space for several overlapping reasons.

#### 1. The backlog corpus has no balance/overview consistency item

The 5 bank-relevant backlog items cover:

- complaint tracking, video KYC and card limit status
- notification preferences and statement sharing
- navigation and search
- phone callback requests
- session expiry wording

None of them proposes a fix for:

- balance accuracy
- account overview mismatch
- transaction history completeness or duplicate transactions
- account details consistency

F11’s strongest cluster is exactly that missing area. The factor is not failing to find a backlog because the text is ambiguous only; there is no matching product intent in the supplied backlog.

#### 2. F11’s factor text is semantically mixed

The narrative name says “Account Balance Consistency and Overview Mismatches,” but the description and representative problems also include selfie verification and statement generation. The D11 provisional label is “Beneficiaries · video kyc · cards · controls.”

That mixture weakens retrieval:

- a balance/overview backlog would match part of F11
- a selfie/KYC backlog would match a different part
- a notification/statement backlog would match a third part
- no single backlog matches the whole factor text

The low semantic coherence score (`6.3576`) is consistent with this.

#### 3. F11 has high prevalence but weak representation

F11 has:

- 200 members, so prevalence is high (`55.2486`)
- 0 problems above the representation threshold
- 100 of 200 memberships flagged ambiguous
- low semantic coherence

This is a “broad but diffuse” factor. It matters to many problems but does not strongly define them. A diffuse factor is harder to match to a focused backlog item.

#### 4. F11 ranks 9th or lower for every backlog

The per-backlog top-8 retention rule means F11 is excluded from `BL-2001` and `BL-2003` at rank 9. It is excluded from `BL-2004` at rank 11 and from `BL-2007` at rank 12. It has zero coverage for `BL-2006`, `BL-2009` and `BL-2010`.

As a result, F11 has no retained finding and therefore no `factor_backlog` link.

#### 5. The report only surfaces uncovered factors at rank 5 or better

The `uncovered_high_priority_factors` list is intentionally limited to ranks 1-5. F11 is rank 10, so its zero coverage is not shown in that report section.

This is the most important visibility issue:

- F11 is uncovered.
- F11 is not high-priority-undercovered by the report’s definition.
- F11 is therefore easy to miss.

## 6. What this does and does not prove

It does prove:

- F11 has substantial customer evidence: 200 members and 995 evidence mentions across its 20 representative problems.
- F11 has no matching backlog in the supplied 7-item backlog upload.
- F11 has no retained finding and no mapping edge to any backlog.
- F11’s best measured coverage is `0.0654`, which is `NOT_COVERED`.
- The report’s `0.0` / `null` representation is a reporting default, not a measured zero.

It does not prove:

- that F11 is the most important product gap
- that F11 causes balance errors
- that F11 should outrank F7 or F3
- that the customer evidence is clean or non-duplicated
- that a production backlog also lacks balance/overview work
- that F11 is a single coherent product theme

The sample backlog contains only 7 items, 2 of which are off-domain. A real product backlog may contain a balance/account-overview item that was not uploaded here.

The appropriate conclusion is narrower:

> Within this uploaded backlog and this factor model, F11 is uncovered white space. Whether that is a true product gap or a factor-quality problem needs human review.

## 7. Data caveats

### “Canonical problem count” is 172, but the feedback run has 362 themes

`RPT-abfba1eb8309` reports `canonical_problem_count: 172`. The feedback run has 362 canonical themes.

This is not a mismatch in the source data. The factor validation report sets the count from the union of all factors’ `supporting_problem_ids`:

- 12 factors x 20 supporting IDs = 240 slots
- duplicate IDs across factors reduce the union to 172 unique problems
- the report’s `canonical_problem_count` is therefore the number of problems used as factor evidence, not the total number of canonical themes

For that reason:

- use `362` for “all canonical themes in the feedback run”
- use `172` for “unique problems referenced by the 12 factors in this report”

### F11’s narrative `problem_count` is not its prevalence

The narrative serialization for D11 contains `problem_count: 362` and `problem_share_pct: 100.0`. That is not the same as the F11 score’s prevalence.

The authoritative factor score row says:

- `N_f = 200`
- `N = 362`
- prevalence = `55.2486`

Use the `factor_prioritisation_scores` row for scoring and `dimension_problem_membership` for membership.

### F11’s semantic review is still unreviewed

The factor nomenclature is approved, but the semantic assessment row has `review_status = UNREVIEWED`. The factor name and the report should therefore be treated as machine-generated evidence until a human reviewer resolves the semantic assessment.

## 8. Recommended next actions

1. **Review F11’s semantic assessment.** The factor name, D11 provisional label and representative set disagree. A human should decide whether the factor is coherent enough to use for coverage decisions.

2. **Split or re-label F11 if needed.** If balance/overview/history and selfie/statement are genuinely separate themes, split the factor and re-run the narrative and prioritisation. If they are one factor, update the description and D11 label so the text used for retrieval reflects the actual content.

3. **Add a balance/account-overview backlog item.** If F11 is a real product gap, add a backlog item covering:
   - balance accuracy after transactions
   - account overview versus statement consistency
   - missing or duplicate transaction history
   - clear error and loading states for balance/overview

4. **Re-run backlog validation after adding the item.** Check whether F11 moves from `NOT_COVERED` to `COVERS` or `PARTIALLY_COVERS`. The coverage should be based on evidence, not on the factor name alone.

5. **Make unseen white space visible.** Add a report view for:
   - factors with no retained finding
   - high-prevalence factors outside the rank-5 gap list
   - “no candidate retained” versus “measured zero coverage”

6. **Persist or expose the full factor/backlog score matrix.** The current report keeps only top-8 findings. Persisting all pairs, or at least the best score per factor/backlog pair, would let analysts distinguish:
   - “not compared”
   - “compared and low”
   - “compared and excluded by top-k”

7. **Add a regression test for the null-versus-zero distinction.** A factor with no retained finding must not be presented as having a measured coverage of `0.0` without a warning.

## 9. Source references

| Concern | File |
|---|---|
| Read-only mapping graph | `backend/app/services/mappings.py` |
| Mapping graph API | `backend/app/api/mapping_routes.py` |
| Mapping UI | `frontend/src/pages/MappingsPage.tsx` |
| Factor-level backlog validation | `backend/app/services/backlog.py` (`_validate_factors`) |
| Coverage formula | `backend/app/services/backlog.py` (`_validate_factors`) |
| Relationship thresholds | `backend/app/services/backlog.py` (`_factor_relationship`) |
| Top-8 finding retention | `backend/app/services/backlog.py` (`item_findings = ... [:8]`) |
| Factor coverage aggregation | `backend/app/services/backlog.py` (`factor_coverage`) |
| High-priority gap filter | `backend/app/services/backlog.py` (`priority_rank <= 5`) |
| Factor score weights | `backend/app/intelligence/factor_prioritisation/calculator.py` |
| Factor score components | `backend/app/intelligence/factor_prioritisation/scoring.py` |
| Factor run orchestration | `backend/app/services/factor_prioritisation.py` |
| Factor narrative generation | `backend/app/intelligence/problem_dimensions/llm/` |
| Report UI | `frontend/src/pages/ReportPage.tsx` |

### Key source locations

- `backend/app/services/mappings.py:14` builds the feedback-theme-factor-backlog graph.
- `backend/app/services/mappings.py:159` loads factor scores and membership links.
- `backend/app/services/mappings.py:212` creates factor-backlog links from report findings only.
- `backend/app/services/backlog.py:446` defines the relationship thresholds.
- `backend/app/services/backlog.py:457` runs factor-level validation.
- `backend/app/services/backlog.py:582` retains only the top 8 findings per backlog.
- `backend/app/services/backlog.py:685` computes `factor_coverage` from retained findings.
- `backend/app/services/backlog.py:723` filters uncovered high-priority factors to ranks 1-5.
- `backend/app/intelligence/factor_prioritisation/calculator.py:20` defines the default 30/25/25/20 weights.
