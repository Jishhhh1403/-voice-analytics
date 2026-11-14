# Factor Evidence Prioritisation Framework
## An evidence-driven approach to prioritising discovered banking customer-problem dimensions

**Project:** Banking Customer Feedback Intelligence Platform  
**Module:** Factor Prioritisation  
**Approach:** Statistical and Semantic Evidence-Based Prioritisation  
**Status:** Currently under implementation

---

## 1. Overview

The Factor Evidence Prioritisation Framework is designed to identify which discovered customer-problem dimensions deserve the greatest analytical and product-management attention.

The platform uses Factor Analysis of Mixed Data (FAMD) to discover underlying dimensions across canonical banking customer problems. These dimensions represent patterns of variation across problem characteristics such as journey, aspect, intent, symptom, transaction state and other structured features.

However, discovering factors alone does not establish which factors should receive priority.

A factor may explain a substantial proportion of variation but represent relatively few canonical problems. Another may cover a larger portion of the problem repository but have weaker statistical representation. Similarly, a statistically significant dimension may not form a sufficiently coherent banking customer-experience theme.

To address this, the proposed prioritisation framework evaluates each factor using four complementary dimensions:

1. Factor Prevalence
2. Statistical Importance
3. Problem Representation Strength
4. Semantic Coherence

These dimensions are combined into a single, explainable priority score.

The approach deliberately uses the information already available in the platform rather than estimating customer or business impacts for which supporting data does not currently exist.

The resulting ranking is called **Factor Evidence Priority**.

---

## 2. Why Factor Prioritisation Is Necessary

FAMD provides a mathematical representation of the relationships and variation present across the canonical problem dataset. It helps identify dimensions that explain recurring patterns across customer problems.

However, the statistical output alone does not provide a complete prioritisation decision.

Consider three hypothetical factors:

- Factor A explains a relatively large proportion of variation but represents a limited number of canonical problems.
- Factor B represents a larger number of canonical problems and has a coherent relationship across banking journeys.
- Factor C has strong statistical representation but contains several semantically different problem patterns.

Simply ranking factors by explained variance would overlook these differences.

Similarly, ranking only by the number of associated problems would ignore the statistical structure discovered by FAMD.

The prioritisation model therefore combines statistical evidence, problem representation and banking-domain interpretation to provide a more balanced assessment.

Its purpose is to answer:

**Which discovered dimensions have the strongest combined evidence in the current canonical problem repository?**

---

## 3. Prioritisation Model

The framework uses four scoring dimensions, each assigned a configurable weight.

| Prioritisation dimension | Weight | What it measures |
|---|---:|---|
| Factor Prevalence | 30% | How broadly the factor is represented across canonical problems. |
| Statistical Importance | 25% | How much variation the factor explains in the FAMD model. |
| Problem Representation Strength | 25% | How meaningfully canonical problems contribute to or are represented by the factor. |
| Semantic Coherence | 20% | How consistently the factor represents a meaningful banking customer-experience theme. |
| **Total** | **100%** | |

The overall factor priority score is:

\[
FS_f = 0.30P_f + 0.25E_f + 0.25R_f + 0.20C_f
\]

Where:

- \(FS_f\): Final Factor Evidence Priority Score.
- \(P_f\): Factor Prevalence Score.
- \(E_f\): Statistical Importance Score.
- \(R_f\): Problem Representation Strength Score.
- \(C_f\): Semantic Coherence Score.

Each component is normalised to a 0–100 scale.

The weights represent the current proposed prioritisation configuration. They are configurable and should be reviewed through sensitivity analysis as the model matures.

---

## 4. The Four Prioritisation Dimensions

### 4.1 Factor Prevalence — 30%

**Objective:** Determine how widely a factor is represented across the canonical problem repository.

Factor prevalence measures the proportion of canonical problems meaningfully associated with a particular factor.

A factor representing a larger share of the problem repository has broader coverage and potentially captures a more widespread pattern in the identified customer problems.

**Calculation:**

\[
P_f = \frac{N_f}{N}\times100
\]

Where:

- \(N_f\): Number of canonical problems associated with factor \(f\).
- \(N\): Total number of canonical problems in the FAMD analysis.

**Example:**

If a factor is associated with 42 out of 162 canonical problems:

\[
P_f = \frac{42}{162}\times100 = 25.93
\]

Its prevalence score is 25.93 before any additional normalisation policy.

**Data used:**

- Factor problem count.
- Factor problem share.
- Factor memberships.
- Canonical problem IDs.

**Interpretation:**

A higher prevalence score indicates that the factor represents a broader portion of the discovered problem repository.

An important implementation consideration is that FAMD produces coordinates for observations across dimensions. The existence of a coordinate does not automatically establish meaningful factor membership. The platform must use a documented and consistent membership rule when calculating prevalence.

### 4.2 Statistical Importance — 25%

**Objective:** Determine how much variation each factor explains within the analysed dataset.

FAMD generates eigenvalues and explained-variance statistics for its dimensions. These indicate the relative amount of variation captured by each dimension.

A factor explaining a larger share of total inertia has greater statistical importance within the fitted FAMD representation.

**Calculation:**

\[
E_f = \frac{\lambda_f}{I}\times100
\]

Where:

- \(\lambda_f\): Eigenvalue of factor \(f\).
- \(I\): Total inertia of the FAMD model.

Where the existing FAMD implementation already provides explained variance using this definition, that output should be reused.

**Data used:**

- Factor eigenvalues.
- Explained variance.
- Cumulative variance.
- Total inertia.
- FAMD run diagnostics.

**Interpretation:**

A higher score means that the dimension captures a greater proportion of variation in the feature matrix.

This is a statistical measure, not a measure of customer severity, financial detriment or regulatory importance.

For example, a factor explaining 24% of variation is statistically more prominent than one explaining 8%. It does not automatically mean that customers experience more harm from the first factor.

### 4.3 Problem Representation Strength — 25%

**Objective:** Understand how meaningfully individual canonical problems are represented along each factor.

FAMD produces problem-level coordinates and contribution information. These outputs help explain the relationship between individual canonical problems and discovered dimensions.

The platform uses:

- Signed problem coordinates.
- Relative squared-coordinate shares.
- Coordinate ranks.
- Row-contribution metadata.
- Positive and negative representative problems.
- Factor-level contribution statistics.

**Key distinction:**

A signed FAMD coordinate represents the position of a canonical problem along a dimension. It is not a probability, causal coefficient or direct membership-strength score.

Positive and negative coordinates indicate opposite directions along the same dimension. A negative coordinate does not automatically imply weak association or negative customer impact.

**Proposed representation measure:**

Use FAMD row-contribution metadata to determine how many canonical problems meet a documented contribution-based representation rule.

\[
R_f = \frac{N_f^*}{N}\times100
\]

Where:

- \(N_f^*\): Number of canonical problems satisfying the representation rule for factor \(f\).
- \(N\): Total canonical problems.

The representation rule must be defined using the actual FAMD contribution methodology and stored as a versioned configuration.

Additional diagnostics include:

- Mean and median row contribution.
- Maximum row contribution.
- Distribution of row contributions.
- Number of represented problems.
- Positive and negative coordinate counts.
- Missing problem-score count.

These diagnostics help distinguish broadly represented dimensions from dimensions dominated by a small number of observations.

**Relative squared-coordinate share:**

The platform also retains the relative squared-coordinate share for each canonical problem:

\[
W_{if} =
\frac{s_{if}^{2}}{\sum_j s_{ij}^{2}}\times100
\]

Where \(s_{if}\) is the coordinate of problem \(i\) on factor \(f\).

This describes the relative squared-coordinate magnitude of a problem across the retained dimensions. It supports problem-level interpretation and exploration but should not be confused with a causal contribution or percentage of the problem explained by a factor.

**Data used:**

- Problem factor scores.
- Signed coordinates.
- Relative squared-coordinate shares.
- Row contributions.
- Coordinate ranks.
- Representative problem IDs.

**Interpretation:**

A higher representation score indicates that a larger proportion of canonical problems meet the defined contribution-based representation rule.

It helps establish whether a factor reflects a broader pattern across the problem repository or is disproportionately influenced by a small number of problems.

### 4.4 Semantic Coherence — 20%

**Objective:** Evaluate whether the factor represents a meaningful and internally coherent banking customer-experience dimension.

Statistical relationships alone do not always produce an immediately interpretable business concept.

For example, a factor may group problems involving payment status, pending transactions and unclear transaction outcomes. Its mathematical representation may be meaningful, but the platform also needs to establish whether these problems form a coherent customer-experience theme.

This component uses Gemini to interpret the factor equations, canonical problem evidence, FAMD contributions and banking-domain context.

The evaluation considers five dimensions:

| Semantic dimension | What is evaluated |
|---|---|
| Journey Coherence | Whether supporting problems have meaningful relationships across banking journey stages. |
| Aspect Coherence | Whether problems relate to compatible banking aspects. |
| Intent Coherence | Whether customer goals and intentions form a meaningful theme. |
| Symptom Coherence | Whether observed customer-facing symptoms are related. |
| Banking-Process Coherence | Whether transaction states and banking process relationships support the interpretation. |

Each dimension receives a score between 0 and 100, supported by explanations and canonical problem references.

**Calculation:**

\[
C_f = \frac{J_f+A_f+I_f+S_f+B_f}{5}
\]

Where:

- \(J_f\): Journey coherence.
- \(A_f\): Aspect coherence.
- \(I_f\): Intent coherence.
- \(S_f\): Symptom coherence.
- \(B_f\): Banking-process coherence.

The initial model assigns equal weights to the five semantic dimensions.

**Data used:**

- Factor equations.
- Representative positive and negative problems.
- Canonical problem titles and statements.
- Journey, aspect and intent.
- Symptom categories.
- Transaction states.
- Variable and category contributions.
- Factor nomenclature and definitions.
- Banking taxonomy and process knowledge.
- Contradictory problem evidence.

**Role of Gemini:**

Gemini acts as a semantic interpretation and evaluation component.

It is responsible for assessing the coherence of the evidence, explaining the assessment and identifying supporting or contradictory canonical problems.

It must not calculate FAMD statistics, change factor coordinates, determine statistical membership or independently calculate the final priority score.

All semantic assessments are structured, evidence-referenced and versioned. Missing information must be represented as unknown rather than treated as evidence of poor coherence.

**Interpretation:**

A higher semantic coherence score indicates that the factor has a more consistent and interpretable banking customer-experience theme.

It does not establish a technical root cause or prove actual customer or business harm.

---

## 5. Final Score and Factor Ranking

Once the four component scores have been calculated, they are combined using the configured weights.

\[
FS_f = 0.30P_f + 0.25E_f + 0.25R_f + 0.20C_f
\]

The resulting score ranges from 0 to 100 when all four components are available and normalised to that range.

**Illustrative example:**

| Component | Factor F1 | Factor F2 | Factor F3 |
|---|---:|---:|---:|
| Prevalence | 90 | 65 | 40 |
| Statistical Importance | 95 | 75 | 50 |
| Representation Strength | 85 | 80 | 60 |
| Semantic Coherence | 80 | 90 | 85 |
| **Final Priority Score** | **88.75** | **76.25** | **56.25** |

The resulting ranking is:

1. F1 — 88.75
2. F2 — 76.25
3. F3 — 56.25

These figures are illustrative and do not represent actual platform results.

The ranking provides a combined assessment of the statistical and semantic evidence supporting each dimension.

It does not establish that the highest-ranked factor represents the greatest customer harm or financial risk.

---

## 6. Evidence Quality and Missing Information

A key design principle is that unavailable information must not be interpreted as zero.

The current platform does not have reliable measurements for:

- Customer severity or frustration.
- Customer trust and effort.
- Churn and retention.
- Customer lifetime value.
- Revenue impact.
- Financial detriment.
- FCA regulatory exposure.
- Cybersecurity and data privacy risk.
- Transaction-level operational impact.

Consequently, these measures are not included in the current numerical prioritisation formula.

Instead, every factor receives an evidence status:

| Status | Meaning |
|---|---|
| VALIDATED | Required statistical and semantic evidence passes the defined checks. |
| PROVISIONAL | A score is available, but some evidence or assessment requirements remain incomplete. |
| INSUFFICIENT_EVIDENCE | There is insufficient information to calculate a defensible score. |
| EXCLUDED | The factor fails a required quality or eligibility condition. |

Where a component is unavailable and provisional scoring is permitted, the remaining component weights can be renormalised.

\[
FS_f^{provisional} =
\frac{\sum_{k\in A}w_kS_{fk}}
{\sum_{k\in A}w_k}
\]

Where \(A\) represents the assessable components.

Evidence coverage must also be calculated and displayed so that users can distinguish a complete score from a provisional one.

A missing component must never be silently converted into a zero.

---

## 7. Implementation Architecture

The prioritisation framework operates as a downstream analytical layer on top of the existing FAMD and canonical problem intelligence pipeline.

The proposed execution flow is:

**Step 1 — FAMD Data Retrieval**

Retrieve completed FAMD runs, factor statistics, eigenvalues, problem coordinates, row contributions and factor equations.

**Step 2 — Statistical Validation**

Validate the analysis run, feature schema, quality gates, factor memberships and problem-score consistency.

**Step 3 — Statistical Scoring**

Calculate factor prevalence, statistical importance and problem representation strength using deterministic calculations.

**Step 4 — Semantic Evaluation**

Construct factor-level evidence payloads and send them to Gemini for structured semantic coherence evaluation.

**Step 5 — Final Prioritisation**

Combine the four component scores using the configured weights. Apply evidence-quality and eligibility rules.

**Step 6 — Persistence**

Store the final scores, component-level evidence, assessment outputs, model versions and ranking.

**Step 7 — Visualisation**

Expose ranked factors and their supporting evidence through the Product Owner and leadership interface.

This separation ensures that statistical calculations remain deterministic while LLM-based interpretation remains independently reviewable.

---

## 8. Explainability and Product Owner Interpretation

A priority score should not be presented as an unexplained ranking.

For every factor, the platform should expose:

- Factor name and business definition.
- Final priority score and rank.
- Four component scores.
- Problem count and prevalence.
- Eigenvalue and explained variance.
- Representation and contribution diagnostics.
- Supporting canonical problems.
- Contradictory canonical problems.
- Factor equation and variable/category contributions.
- Semantic interpretation.
- Evidence status and data limitations.

This allows a Product Owner to understand not only which factors rank highest, but also why they received that position.

For example:

A factor may rank highly because it represents a large share of canonical problems and explains a substantial proportion of variation, while also demonstrating a coherent relationship across payment journeys.

Another factor may rank lower because its supporting problems are less broadly represented or its semantic interpretation is less consistent.

The component breakdown makes these differences visible and supports informed product discussions.

---

## 9. Governance, Reproducibility and Validation

The prioritisation model must be reproducible and auditable.

Each execution should retain:

- FAMD run ID.
- Feature-schema version.
- Selected and excluded features.
- FAMD parameters and diagnostics.
- Membership-rule version.
- Scoring-model version.
- Component weights.
- Semantic prompt version.
- Gemini model version.
- Component-level scores.
- Final priority score.
- Evidence references.
- Eligibility and review status.

Historical runs must remain available so that changes in FAMD outputs, feature schemas, semantic assessments or scoring weights can be analysed.

Sensitivity analysis should also be performed using alternative component weights to assess whether the ranking is robust or heavily dependent on the initial weighting assumptions.

The statistical components should be tested independently. Semantic assessments should be evaluated for consistency, evidence grounding and repeatability.

---

## 10. Current Scope and Future Evolution

The current implementation focuses exclusively on the statistical and semantic evidence available within the existing customer feedback intelligence platform.

It establishes a defensible first-stage prioritisation framework without assuming access to customer-level operational, financial or regulatory datasets.

The framework is designed to evolve as additional evidence becomes available.

Future extensions may introduce separately validated measures for:

- Customer severity and frustration.
- Customer effort and trust.
- Churn and retention impact.
- Financial detriment and revenue exposure.
- FCA-related regulatory obligations and customer-protection risk.
- Security and data privacy exposure.
- Transaction-level operational impact.

These measures should be introduced as new, evidence-backed prioritisation dimensions under a separately versioned scoring model.

The current Factor Evidence Priority score should not be retrospectively interpreted as a customer-impact or business-risk score.

---

## 11. Conclusion

The Factor Evidence Prioritisation Framework provides a structured approach to ranking the dimensions discovered through FAMD.

By combining factor prevalence, statistical importance, problem representation strength and semantic coherence, it moves beyond ranking factors using a single statistical measure.

Its key strength is the integration of quantitative FAMD evidence with structured banking-domain interpretation while maintaining a clear separation between statistical findings and business-impact assumptions.

The resulting framework is:

- **Statistically grounded:** Uses existing FAMD outputs and contribution metadata.
- **Semantically informed:** Incorporates banking journeys, customer intent, symptoms and process context.
- **Explainable:** Retains the evidence behind every component score.
- **Reproducible:** Versions scoring rules, model runs and semantic assessments.
- **Extensible:** Can incorporate customer, operational, financial and regulatory evidence when those datasets become available.

**The intended outcome is a transparent and evidence-backed ranking of discovered banking customer-problem dimensions, helping Product Owners identify which underlying problem themes deserve the greatest attention based on the evidence currently available.**