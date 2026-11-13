"""Versioned Pydantic contracts for LLM factor interpretation.

The contracts deliberately separate statistical facts (coordinates, equations,
variable contributions) from model-generated interpretation. Statistical fields
are populated or overwritten by the orchestration layer so the model cannot
alter FAMD coordinates, dimension IDs or factor assignments.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Alignment = Literal["strong", "moderate", "weak", "opposite"]
Clarity = Literal["clear", "ambiguous"]
NomenclatureStatus = Literal["CONFIDENT", "PROVISIONAL", "AMBIGUOUS", "REVIEW_REQUIRED"]
CrossReviewStatus = Literal["PASSED", "REVISE", "HUMAN_REVIEW"]


class ProblemDimensionObservation(BaseModel):
    """One canonical problem interpreted against one retained FAMD dimension."""

    canonical_problem_id: str
    problem_summary: str = Field(min_length=1, max_length=1200)
    dimension_id: str
    factor_id: str
    current_dimension_coordinate: float
    equation_text: str
    banking_journey_interpretation: str = Field(min_length=1, max_length=1200)
    customer_action: str = Field(min_length=0, max_length=600)
    customer_intent: str = Field(min_length=0, max_length=600)
    observed_symptom: str = Field(min_length=0, max_length=600)
    transaction_state: str = Field(min_length=0, max_length=600)
    alignment: Alignment
    supporting_evidence: list[str] = Field(default_factory=list, max_length=12)
    contradictory_evidence: list[str] = Field(default_factory=list, max_length=12)
    clarity: Clarity
    relevance_explanation: str = Field(min_length=1, max_length=1200)
    confidence: float = Field(ge=0.0, le=1.0)


class ProblemObservationBatch(BaseModel):
    observations: list[ProblemDimensionObservation] = Field(default_factory=list, max_length=24)


class DimensionEvidenceAggregation(BaseModel):
    """Consolidated evidence for a dimension before naming."""

    emerging_construct: str = Field(min_length=1, max_length=600)
    recurring_customer_experiences: list[str] = Field(default_factory=list, max_length=20)
    common_aspects: list[str] = Field(default_factory=list, max_length=20)
    common_journey_nodes: list[str] = Field(default_factory=list, max_length=20)
    common_intents: list[str] = Field(default_factory=list, max_length=20)
    common_symptoms: list[str] = Field(default_factory=list, max_length=20)
    common_transaction_states: list[str] = Field(default_factory=list, max_length=20)
    customer_consequences: list[str] = Field(default_factory=list, max_length=20)
    supporting_variables: list[str] = Field(default_factory=list, max_length=20)
    supporting_categories: list[str] = Field(default_factory=list, max_length=20)
    strongly_aligned_problem_ids: list[str] = Field(default_factory=list, max_length=50)
    oppositely_positioned_problem_ids: list[str] = Field(default_factory=list, max_length=50)
    outlier_problem_ids: list[str] = Field(default_factory=list, max_length=50)
    non_fitting_problem_ids: list[str] = Field(default_factory=list, max_length=50)
    distinguishing_characteristics: list[str] = Field(default_factory=list, max_length=20)
    evidence_references: list[str] = Field(default_factory=list, max_length=100)
    confidence: float = Field(ge=0.0, le=1.0)


class FactorNomenclatureProposal(BaseModel):
    """Business nomenclature proposed for one retained dimension."""

    factor_id: str
    dimension_id: str
    proposed_name: str = Field(min_length=1, max_length=160)
    short_name: str = Field(min_length=1, max_length=80)
    formal_definition: str = Field(min_length=1, max_length=2000)
    business_interpretation: str = Field(min_length=1, max_length=2000)
    banking_domain: str = Field(min_length=1, max_length=160)
    journey_scope: str = Field(min_length=0, max_length=600)
    core_customer_experience: str = Field(min_length=1, max_length=1000)
    supporting_variables: list[str] = Field(default_factory=list, max_length=20)
    supporting_categories: list[str] = Field(default_factory=list, max_length=20)
    representative_problem_ids: list[str] = Field(default_factory=list, max_length=50)
    contradictory_problem_ids: list[str] = Field(default_factory=list, max_length=50)
    distinguishing_characteristics: str = Field(min_length=0, max_length=1200)
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_explanation: str = Field(min_length=1, max_length=1200)
    nomenclature_status: NomenclatureStatus


class CrossDimensionFinding(BaseModel):
    dimension_ids: list[str] = Field(default_factory=list, max_length=10)
    issue: str = Field(min_length=1, max_length=1200)
    recommendation: str = Field(min_length=1, max_length=1200)
    recommended_names: dict[str, str] = Field(default_factory=dict)
    requires_human_review: bool = True


class CrossDimensionReview(BaseModel):
    status: CrossReviewStatus
    findings: list[CrossDimensionFinding] = Field(default_factory=list, max_length=30)
    summary: str = Field(min_length=1, max_length=2000)


class TaxonomyContext(BaseModel):
    version: str
    banking_domains: list[dict[str, object]]
    journey_context_fields: list[str]
    process_knowledge: list[dict[str, object]]
    missing_supported_domains: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)


class FactorNarrativeFeature(BaseModel):
    """One variable or category contribution behind a factor narrative."""

    feature_name: str = Field(min_length=1, max_length=240)
    feature_type: Literal["variable", "category"] = "variable"
    contribution_pct: float = Field(ge=0.0, le=100.0)
    direction_summary: str = Field(default="", max_length=240)


class FactorNarrative(BaseModel):
    """LLM-authored factor name, description and grounded business explanation."""

    factor_id: str
    dimension_id: str
    name: str = Field(min_length=1, max_length=160)
    short_name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=2000)
    business_interpretation: str = Field(min_length=1, max_length=2000)
    banking_domain: str = Field(min_length=1, max_length=160)
    journey_scope: str = Field(default="", max_length=600)
    core_customer_experience: str = Field(min_length=1, max_length=1000)
    problem_count: int = Field(ge=0)
    problem_share_pct: float = Field(ge=0.0, le=100.0)
    explained_variance_pct: float | None = None
    cumulative_variance_pct: float | None = None
    mean_coefficient: float
    mean_abs_coefficient: float = Field(ge=0.0)
    min_coefficient: float
    max_coefficient: float
    max_abs_coefficient: float = Field(ge=0.0)
    top_features: list[FactorNarrativeFeature] = Field(default_factory=list, max_length=20)
    positive_problem_pattern: str = Field(min_length=1, max_length=1200)
    negative_problem_pattern: str = Field(min_length=1, max_length=1200)
    representative_problem_ids: list[str] = Field(default_factory=list, max_length=50)
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_explanation: str = Field(min_length=1, max_length=1200)


class FactorNarrativeSerializationProposal(BaseModel):
    """One agent-authored narrative serialization across all retained factors."""

    summary: str = Field(min_length=1, max_length=3000)
    factors: list[FactorNarrative] = Field(min_length=1, max_length=30)


class FactorEquationRecord(BaseModel):
    """Complete equation and evidence for one canonical problem."""

    canonical_problem_id: str
    title: str
    problem_statement: str | None = None
    canonical_description: str | None = None
    journey: dict[str, object] = Field(default_factory=dict)
    aspect: str | None = None
    customer_intent: str | None = None
    symptom_category: str | None = None
    symptoms: list[object] = Field(default_factory=list)
    transaction_state: str | None = None
    equation_text: str
    coefficients: list[dict[str, object]] = Field(default_factory=list)
    dimension_evidence: dict[str, dict[str, object]] = Field(default_factory=dict)
    missingness: dict[str, object] = Field(default_factory=dict)
    data_quality_status: str = "UNKNOWN"


class EquationSerializationContract(BaseModel):
    schema_version: str
    analysis_run_id: str
    feedback_run_id: str | None = None
    model_version: str | None = None
    retained_dimension_ids: list[str]
    coefficient_interpretation: str
    problems: list[FactorEquationRecord]
