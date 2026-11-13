# Canonical-Problem Factor Coefficient Analysis

This layer explains how each canonical customer problem relates to the latent
dimensions discovered by FAMD (Factor Analysis of Mixed Data). It is additive:
it does not change canonical problems, priorities, clustering or the MDS theme
map.

## Method

1. Build one versioned feature row per canonical problem from persisted fields.
2. Run data-quality gates and exclude all-null, constant or forbidden features.
3. Median-impute numeric values and use an explicit `__MISSING__` category for
   categorical values during fitting only.
4. Fit FAMD with a configured random state and retain the configured number of
   components.
5. Persist signed row coordinates as problem-factor coefficients, together with
   variable/category contributions, relative squared-coordinate shares and
   readable equations.
6. Require analyst review of each proposed factor name before publication.

## Equations

For canonical problem `CP_i` and retained dimensions `F1..Fk`:

```text
CP_i = beta_i1*F1 + beta_i2*F2 + ... + beta_ik*Fk
```

`beta_ij` is the FAMD row coordinate for problem `i` on dimension `j`. The sign
is preserved. A negative coefficient means the problem lies on the opposite side
of the same latent pattern; it is not a separate dimension.

A descriptive squared-coordinate share is also recorded:

```text
relative_squared_coordinate_share_pct_ij
  = s_ij^2 / sum_j(s_ij^2) * 100
```

The share is null when every coordinate for the problem is zero. It describes
the relative magnitude of squared coordinates within one problem only. It is not
a causal contribution, a percentage of customer impact, or a variance explained
by that problem.

## Factor names

Proposed names are generated from the highest-contribution category levels and
variables for each dimension. They are drafts for domain-expert review, not
hardcoded business concepts. Analysts can approve, rename, request revision or
reject each factor. Publication requires every retained factor to be approved.

## Data availability

The current source model does not persist every attribute named in the broader
product specification, including severity, frustration, trust, churn, CLV,
regulatory, security and revenue-risk scores. Those attributes are not
fabricated. Available features include journey module/feature/stage, aspect,
symptom category, customer intent, evidence volume, distinct customers, negative
share, repeat complaints, source diversity, effort, outcome failure, negative
emotion, volume/customer growth, negative-share change, assessment velocity and
evidence confidence. Features that are unavailable, all-null or constant are
excluded and reported on the run.

## Interpretation caveats

- FAMD row coordinates are associations in latent-dimension space, not causal
  effects, regression betas, severity scores or priority scores.
- Retained component count is a modelling decision supported by interpretability
  and stability, not a fixed variance threshold.
- Low explained inertia can still produce useful descriptive structure, but it
  must not be presented as a complete explanation of problem behaviour.
- Proposed labels are provisional until reviewed. Draft runs must not be
  presented as approved findings.
- Relative squared-coordinate shares are descriptive decompositions, not causal
  contributions.

## API and UI

Run-scoped endpoints:

- `GET /api/v1/problem-dimensions/runs/{run_id}/coefficients`
- `GET /api/v1/problem-dimensions/runs/{run_id}/coefficients.csv`
- `GET /api/v1/problem-dimensions/runs/{run_id}/variables`
- `GET /api/v1/problem-dimensions/runs/{run_id}/problems/{problem_id}/profile`

Spec-compatible aliases are available under `/api/v1/factor-analysis/...`.

The Problem dimensions page shows named factors and a signed coefficient matrix
with CSV export. Problem detail pages show the problem's signed equation and
relative shares. Draft/interpretation warnings remain visible until the run is
reviewed and published.
