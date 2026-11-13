# LLM factor naming from factor equations

FAMD remains the numerical source of truth. The LLM names and interprets
retained factors; it never changes coordinates, dimension IDs, factor
assignments, problem priorities or statistical output.

There are no deterministic business factor names. After FAMD completes, one
complete factor-equation payload is built for each retained factor and sent to
one structured nomenclature call per factor. The factors remain unnamed until
the LLM or an analyst supplies a name.

## Configuration

Gemini is the default provider:

```bash
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-3.5-flash-lite

PROBLEM_DIMENSION_LLM_ENABLED=true
PROBLEM_DIMENSION_LLM_PROVIDER=gemini
PROBLEM_DIMENSION_LLM_FALLBACK_PROVIDER=
PROBLEM_DIMENSION_LLM_TEMPERATURE=0.1
PROBLEM_DIMENSION_LLM_MAX_OUTPUT_TOKENS=8192
PROBLEM_DIMENSION_LLM_TIMEOUT_SECONDS=180
PROBLEM_DIMENSION_LLM_MAX_ATTEMPTS=3
PROBLEM_DIMENSION_LLM_CROSS_REVIEW=true

PROBLEM_DIMENSION_FACTOR_NOMENCLATURE_PROMPT_VERSION=dimension-factor-equation-nomenclature-1.0.0
PROBLEM_DIMENSION_FACTOR_NARRATIVE_PROMPT_VERSION=dimension-factor-narrative-1.1.0
PROBLEM_DIMENSION_FACTOR_NARRATIVE_MODEL_FALLBACKS=gemini-3.1-flash-lite
PROBLEM_DIMENSION_FACTOR_NARRATIVE_MAX_OUTPUT_TOKENS=16384
PROBLEM_DIMENSION_FACTOR_NARRATIVE_TIMEOUT_SECONDS=600
PROBLEM_DIMENSION_FACTOR_NARRATIVE_RETRY_ATTEMPTS=2
PROBLEM_DIMENSION_CROSS_REVIEW_PROMPT_VERSION=dimension-cross-review-1.0.0
```

To avoid Gemini quota/rate limits, use any OpenAI-compatible endpoint such as
Ollama or vLLM:

```bash
PROBLEM_DIMENSION_LLM_PROVIDER=openai_compatible
PROBLEM_DIMENSION_LLM_BASE_URL=http://localhost:11434/v1
PROBLEM_DIMENSION_LLM_MODEL=llama3.1
PROBLEM_DIMENSION_LLM_API_KEY=local
```

Existing `OPENAI_BASE_URL`, `OPENAI_MODEL` and `OPENAI_API_KEY` values are used
as fallbacks when the `PROBLEM_DIMENSION_LLM_*` endpoint fields are blank.

A fallback provider can be configured independently:

```bash
PROBLEM_DIMENSION_LLM_PROVIDER=gemini
PROBLEM_DIMENSION_LLM_FALLBACK_PROVIDER=openai_compatible
PROBLEM_DIMENSION_LLM_BASE_URL=http://localhost:11434/v1
PROBLEM_DIMENSION_LLM_MODEL=llama3.1
```

`auto` selects Gemini when `GEMINI_API_KEY` exists, otherwise the
OpenAI-compatible endpoint. Quota and `429` responses fail fast instead of
sleeping through every retry.

## Pipeline

1. **Deterministic FAMD** saves coordinates, contributions, equations and
   technical dimension scaffolding. Definitions have no business name.
2. **Factor equation builder** (`llm/factor_equations.py`) creates one payload
   per retained factor containing:
   - eigenvalue and explained/cumulative variance;
   - ranked variable and category contributions;
   - representative problem equations with full coefficients;
   - positively and negatively positioned problem equations;
   - representative/positive/negative problem IDs;
   - missingness and the signed-coordinate interpretation constraint.
3. **Factor nomenclature** (`llm/nomenclature.py`) makes exactly one structured
   call per factor using the full factor equation, banking taxonomy context,
   other retained factor summaries and existing approved names.
4. **Deterministic validation** (`llm/validation.py`) rejects technical names,
   unsupported evidence references, causal language and overlapping names.
5. **Cross-factor review** optionally checks meaning overlap and may recommend
   revised names or human review. It cannot merge or reassign factors.
6. **Apply and persist** (`llm/pipeline.py`) writes the proposal to the
   definition and audit tables. Names remain `DRAFT` unless review is disabled.

The pipeline does not make per-problem or per-dimension aggregation LLM calls.
The call count is therefore approximately one nomenclature call per retained
factor, plus at most one optional cross-review call.

## Narrative serialization agent

The **Narrative serialization** page uses a separate LangChain agent over the
whole factor run. It sends every canonical problem equation and coefficient,
complete factor statistics, and the repository banking taxonomy in one grounded
session. The agent can call tools for factor statistics, problem equations and
taxonomy context.

`llm/narrative_agent.py` uses `create_agent`, a LangChain chat model and
`FactorNarrativeSerializationProposal` as the structured response schema. The
structured object covers every retained factor with a name, description,
business interpretation, domain, journey scope, problem patterns, confidence
and representative problems.

Deterministic statistics are merged back after the model responds:
`problem_count`, `problem_share_pct`, explained/cumulative variance, coefficient
means/min/max and top feature percentages always come from the FAMD run. The
agent cannot alter them. Generation is persisted in
`dimension_narrative_serializations`; it is not the numeric source of truth.

Generated names are applied to non-approved definitions as `DRAFT` with
`nomenclature_source=LANGCHAIN_AGENT`. Approved analyst names are preserved.

## Structured provider contracts

All providers return JSON validated by `FactorNomenclatureProposal` or
`CrossDimensionReview`.

| Stage | Schema | Prompt version |
| --- | --- | --- |
| Factor nomenclature | `FactorNomenclatureProposal` | `dimension-factor-equation-nomenclature-1.0.0` |
| Cross-factor review | `CrossDimensionReview` | `dimension-cross-review-1.0.0` |

The proposal contains the factor/dimension IDs, proposed and short names,
formal definition, business interpretation, banking domain, journey scope, core
customer experience, supporting variables/categories, representative and
contradictory problem IDs, distinguishing characteristics, confidence and
nomenclature status.

The orchestration layer overwrites trusted IDs after model output, so the model
cannot alter factor assignments or statistical facts.

## Persistence and resume

The factor payload is stored in `dimension_evidence_aggregations` with the
`factor-equation-1.0.0` schema version. Proposals remain in
`dimension_nomenclature_proposals`; processing state remains in
`dimension_llm_processing`.

`POST .../interpretation/regenerate` with `{"force": false}` reuses successful
proposals. Cross-review is skipped when nothing changed and reviews already
exist. `force=true` regenerates while preserving analyst approval decisions.

Every failure is recorded. A failed factor stays unnamed; there is no
deterministic name fallback. Publication requires non-empty approved names.

## API

- `GET /api/v1/problem-dimensions/runs/{run_id}/interpretation` - provider
  status, prompt versions, processing rows, proposals and run summary.
- `GET /api/v1/problem-dimensions/runs/{run_id}/dimensions/{dimension_id}/interpretation`
  - processing state, the stored factor equation and the proposal.
- `POST /api/v1/problem-dimensions/runs/{run_id}/interpretation/regenerate` -
  resume or force regeneration.
- `GET /api/v1/problem-dimensions/runs/{run_id}/narrative-serialization` -
  latest LangChain factor narrative for the run.
- `POST /api/v1/problem-dimensions/runs/{run_id}/narrative-serialization` -
  run the agent over all problem equations, factor statistics and taxonomy.

Review and publication endpoints are unchanged.

## Portfolio serialization

Portfolio narrative serialization resolves names in this order:

1. approved/published analyst name;
2. LLM proposal (`APPROVED`, `PROVISIONAL` or `UNREVIEWED`).

MDS is not part of the portfolio narrative serialization or workflow. MDS
coordinates and neighbours are not sent to the narrative model and no
portfolio run is bound to an MDS snapshot. Standalone MDS APIs remain available.

## Review and publication

- LLM names are `DRAFT` by default.
- Cross-review revisions are marked `REVIEW_REQUIRED`.
- Every retained factor must be approved and named before publication.
- LLM failure never publishes, approves, renames or replaces an analyst
  decision.

## Verification

```bash
.venv/bin/python -m pytest tests/intelligence/problem_dimensions/test_llm_interpretation.py -q
.venv/bin/python -m pytest tests/intelligence/problem_dimensions tests/intelligence/portfolio -q
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check backend/app tests
```

Tests use a fake structured provider and disable live LLM calls. Automated tests
never depend on Gemini network access or quota.

## Limitations

- Model output is advisory until analyst approval.
- Naming cost is proportional to retained factors, not problems.
- Live provider availability, quota and rate limits remain deployment concerns;
  configure a local/fallback provider when needed.
- Taxonomy coverage is finite. Missing domains are reported, never invented.
- Signed FAMD coordinates are descriptive positions, not causal effects or
  percentage impacts.
- Prompt-injection risk is mitigated with untrusted-data framing and
  deterministic validation, not eliminated.
