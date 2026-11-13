# Problem portfolio narrative

The portfolio layer turns an approved factor run and a completed MDS snapshot into a deterministic statistical payload, then optionally asks Gemini for a grounded narrative over that payload.

## Sources of truth

- Canonical problems, measurements and priorities from the feedback run.
- Approved or published factor names and signed FAMD coefficients from the factor run.
- MDS `x`/`y` coordinates. Portfolio neighbour distances are Euclidean distances in raw MDS coordinate space; the MDS input distance metric remains recorded separately.
- Backlog coverage only when a validation report exists.

Missing measurements remain `null` with their persisted status. They are never converted to zero. Attributes such as severity, churn risk, CLV, revenue at risk, complaint cost, resolution time, NPS and CSAT are listed as unavailable and must not be inferred.

## Deterministic serialization

`backend/app/intelligence/portfolio/serialization.py` builds a versioned payload containing:

- source identifiers and counts;
- available and unavailable attributes;
- approved factor nomenclature and factor profiles;
- portfolio summary counts and provisional factor names;
- per-problem measurements, priority, signed factors, equation, MDS point, Euclidean neighbours and coverage;
- MDS relationship rows, data-quality warnings and interpretation constraints.

The canonical JSON is sorted and hashed with SHA-256. The serialization ID is `SER-<first 20 hash characters>-<run suffix>`; the full content hash remains deterministic. Serialization never depends on narrative text.

The full serialization remains persisted. The model receives a deterministic, token-bounded context built from it: complete factor nomenclature and profiles, every problem in a compact index, and detailed evidence for the highest-priority problems. The prompt never receives multi-megabyte raw payloads.

## Narrative provider

`backend/app/intelligence/portfolio/narrative.py` uses the official `google-genai` package. Configuration:

```bash
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-3.8-flash
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
- business interpretation of MDS axes;
- ungrounded problem or factor references;
- unqualified provisional factors;
- missing values described as zero;
- factor coverage.

Validation status is `PASSED`, `WARNING` or `FAILED`. `WARNING` is accepted; `FAILED` triggers a corrective retry up to `PORTFOLIO_NARRATIVE_MAX_ATTEMPTS`.

## Regeneration

`POST /api/v1/problem-portfolio/runs/{run_id}/narrative/regenerate` reloads the stored serialization and generates a new narrative. It does not rerun MDS, FAMD, measurements or prioritisation. Narratives and validation results are append-only.

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
