# Narrative serialization

The Narrative serialization page is run from factor-analysis history. It shows
the complete customer problem factor-coefficient matrix, including every
identified problem, with factor headings only (`F1`, `F2`, ...). One action runs
a LangChain agent over all problem equations, factor coefficients, factor
statistics and the repository banking taxonomy. The agent names and describes
every retained factor and returns problem coverage, variance, coefficient and
feature-contribution narratives in one grounded section.

The portfolio-run serialization and Gemini narrative APIs remain available for
API consumers and deterministic portfolio publication.

## Sources of truth

- Canonical problems, measurements and priorities from the feedback run.
- Factor names and signed FAMD coefficients from the selected factor run.
- Repository banking taxonomy for agent naming and interpretation.
- Backlog coverage only when a validation report exists.

Missing measurements remain `null` with their persisted status. They are never converted to zero. Attributes such as severity, churn risk, CLV, revenue at risk, complaint cost, resolution time, NPS and CSAT are listed as unavailable and must not be inferred.

## Deterministic serialization

`backend/app/intelligence/portfolio/serialization.py` builds a versioned payload containing:

- source identifiers and counts;
- available and unavailable attributes;
- approved factor nomenclature and factor profiles;
- portfolio summary counts and provisional factor names;
- per-problem measurements, priority, signed factors, equation and coverage;
- data-quality warnings and interpretation constraints.

The canonical JSON is sorted and hashed with SHA-256. The serialization ID is `SER-<first 20 hash characters>-<run suffix>`; the full content hash remains deterministic. Serialization never depends on narrative text.

The full serialization remains persisted. The model receives a deterministic, token-bounded context built from it: complete factor nomenclature and profiles, every problem in a compact index, and detailed evidence for the highest-priority problems. The prompt never receives multi-megabyte raw payloads.

## Factor narrative agent

`backend/app/intelligence/problem_dimensions/llm/narrative_agent.py` implements
the page action as a LangChain `create_agent` workflow. The evidence bundle
contains:

- every canonical problem equation and signed coefficient vector for the run;
- exact factor statistics: problem count/share, explained and cumulative
  variance, mean/min/max coefficients and top feature percentages;
- complete banking taxonomy context and journey mappings;
- prompt, model, agent and taxonomy versions.

The agent has tools for factor statistics, paginated problem equations and
taxonomy lookup. Its structured response (`FactorNarrativeSerializationProposal`)
must cover every factor exactly once. Names must be business language, not
`F1`/`D1` identifiers. Deterministic statistics are overwritten from the
evidence after generation; model-authored numbers are never trusted.

Generation is persisted in `dimension_narrative_serializations` with a content
hash. `GET /api/v1/problem-dimensions/runs/{run_id}/narrative-serialization`
returns the latest result and `POST` runs the agent again. Generated names are
applied to non-approved definitions as `DRAFT`; approved names are preserved.

Configuration:

```bash
PROBLEM_DIMENSION_FACTOR_NARRATIVE_PROMPT_VERSION=dimension-factor-narrative-1.1.0
PROBLEM_DIMENSION_FACTOR_NARRATIVE_MODEL_FALLBACKS=gemini-3.1-flash-lite
PROBLEM_DIMENSION_FACTOR_NARRATIVE_MAX_OUTPUT_TOKENS=16384
PROBLEM_DIMENSION_FACTOR_NARRATIVE_TIMEOUT_SECONDS=600
PROBLEM_DIMENSION_FACTOR_NARRATIVE_RETRY_ATTEMPTS=2
```

Transient transport failures (SSL EOF, connection reset, timeout, 5xx) and
invalid structured output are retried with backoff. Quota/rate-limit responses
are not retried against the same model; the agent moves to the configured
fallback provider, if any. API errors are stored and displayed as concise
messages instead of raw provider payloads.

## Narrative provider

`backend/app/intelligence/portfolio/narrative.py` uses the official `google-genai` package. Configuration:

```bash
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-3.5-flash-lite
PORTFOLIO_NARRATIVE_PROVIDER=gemini
PORTFOLIO_NARRATIVE_MAX_ATTEMPTS=3
PORTFOLIO_NARRATIVE_TEMPERATURE=0.2
PORTFOLIO_NARRATIVE_MAX_OUTPUT_TOKENS=8000
PORTFOLIO_NARRATIVE_TIMEOUT_SECONDS=180
```

The response uses `PortfolioNarrative` from `contracts.py` as a Pydantic `response_schema` with JSON response mode. If the provider is not configured, the run remains `SERIALIZED`, the serialization is available, and an `UNAVAILABLE` narrative row is stored.

## Validation

`backend/app/intelligence/portfolio/validation.py` checks narrative prose for:

- technical IDs such as `Factor 1`, `F1`, `D1` or `CP-...`;
- factor names that are not approved business names;
- causal language around FAMD coefficients or coordinate shares;
- ungrounded problem or factor references;
- unqualified provisional factors;
- missing values described as zero;
- factor coverage.

Validation status is `PASSED`, `WARNING` or `FAILED`. `WARNING` is accepted; `FAILED` triggers a corrective retry up to `PORTFOLIO_NARRATIVE_MAX_ATTEMPTS`.

## Regeneration

`POST /api/v1/problem-portfolio/runs/{run_id}/narrative/regenerate` reloads the stored serialization and generates a new narrative. It does not rerun FAMD, measurements or prioritisation. Narratives and validation results are append-only.

## API

- `GET /api/v1/problem-portfolio/status`
- `POST /api/v1/problem-portfolio/runs`
- `GET /api/v1/problem-portfolio/runs`
- `GET /api/v1/problem-portfolio/runs/{run_id}`
- `GET /api/v1/problem-portfolio/runs/{run_id}/serialization`
- `GET /api/v1/problem-portfolio/runs/{run_id}/narrative`
- `POST /api/v1/problem-portfolio/runs/{run_id}/narrative/regenerate`
- `GET /api/v1/problem-portfolio/runs/{run_id}/validation`
- `GET /api/v1/problem-portfolio/latest`
- `GET /api/v1/problem-portfolio/latest/narrative`

The frontend route is `/portfolio`.
