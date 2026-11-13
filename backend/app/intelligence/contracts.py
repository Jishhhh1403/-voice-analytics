from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Sentiment = Literal["positive", "negative", "neutral", "mixed"]
Effort = Literal["low", "medium", "high", "unknown"]
Outcome = Literal["completed", "failed", "blocked", "abandoned", "workaround_used", "unknown"]
Relationship = Literal[
    "ADDRESSES",
    "PARTIALLY_ADDRESSES",
    "RELATED_BUT_NOT_SOLVING",
    "NO_CLEAR_RELATIONSHIP",
    "CONTRADICTS_OR_OUT_OF_SCOPE",
    "NEEDS_REVIEW",
]
Alignment = Literal["strong", "partial", "weak", "unsupported", "needs_review"]


class CleanFeedback(BaseModel):
    feedback_id: str
    source_feedback_id: str | None = None
    submitted_at: str | None = None
    source_type: str
    source_channel: str
    platform: str
    app_version: str | None = None
    language: str = "en"
    language_confidence: float = 0.0
    synthetic_customer_ref: str | None = None
    rating: int | None = None
    feedback_title: str = ""
    feedback_text_redacted: str
    # Original (pre-redaction) text is preserved for provenance and never
    # returned by analytics APIs. Redacted text is the only evidence source.
    feedback_text_original: str | None = None
    content_fingerprint: str
    duplicate_group_id: str | None = None
    duplicate_type: str | None = None
    quality_flags: list[str] = Field(default_factory=list)
    pii_types: list[str] = Field(default_factory=list)
    is_synthetic: bool = True


class ExtractedInsight(BaseModel):
    insight_id: str
    feedback_id: str
    sentence_index: int
    customer_intent: str | None = None
    intents: list[str] = Field(default_factory=list)
    aspect: str | None = None
    aspects: list[str] = Field(default_factory=list)
    journey_node_id: str | None = None
    reported_problem: str | None = None
    reported_symptom: str | None = None
    symptom_category: str | None = None
    sentiment: Sentiment = "neutral"
    sentiment_score: float = 0.0
    emotion: str = "none"
    customer_effort: Effort = "unknown"
    reported_outcome: Outcome = "unknown"
    evidence_span: str
    evidence_verified: bool = True
    technical_root_cause: str = "unknown"
    language: str = "en"
    model_id: str = "rules-v1"
    prompt_version: str = "rules-2.0"
    schema_version: str = "1.0.0"
    extraction_timestamp: str
    extraction_method: str = "rules"
    confidence: float = 0.5
    field_confidence: dict[str, float] = Field(default_factory=dict)
    human_review_status: str = "unreviewed"
    cluster_id: str | None = None
    embedding_json: str | None = None
    is_problem: bool = False

    @field_validator("evidence_span")
    @classmethod
    def evidence_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("evidence_span must not be empty")
        return value


class ProblemDraft(BaseModel):
    problem_id: str
    signature: str
    title: str = Field(min_length=3, max_length=160)
    problem_statement: str = Field(min_length=3, max_length=400)
    canonical_description: str | None = None
    customer_intent: str | None = None
    aspect: str | None = None
    symptom_category: str | None = None
    journey_node_id: str | None = None
    symptoms: list[str] = Field(default_factory=list)
    evidence_count: int = 0
    distinct_customers: int = 0
    negative_count: int = 0
    first_seen: str | None = None
    last_seen: str | None = None
    cluster_id: str | None = None
    lifecycle_status: str = "candidate"
    validation_status: str = "candidate"
    human_review_status: str = "unreviewed"
    discovery_confidence: float = 0.0
    embedding_ref: str | None = None
    model_metadata: dict[str, str] = Field(default_factory=dict)
    parent_problem_id: str | None = None


class BacklogProfile(BaseModel):
    backlog_id: str
    title: str
    description: str
    acceptance_criteria: str = ""
    acceptance_criteria_items: list[str] = Field(default_factory=list)
    product_area: str | None = None
    priority: str | None = None
    business_goal: str | None = None
    intended_outcome: str | None = None
    customer_intent: str | None = None
    target_feature: str | None = None
    target_journey: str | None = None
    functional_scope: str | None = None
    organisational_objective: str | None = None
    source_system: str | None = None
    intents: list[str] = Field(default_factory=list)
    aspects: list[str] = Field(default_factory=list)
    journey_node_id: str | None = None
    covered_symptoms: list[str] = Field(default_factory=list)
    tokens: list[str] = Field(default_factory=list)
    extraction_provider: str = "rules"
    model_version: str = "rules-v1"


class ValidationFindingContract(BaseModel):
    finding_id: str
    backlog_id: str
    problem_id: str | None = None
    relationship: Relationship
    rationale: str
    alignment_score: float
    supporting_feedback_count: int = 0
    evidence: list[dict] = Field(default_factory=list)
    journey_node_id: str | None = None
    ac_coverage: float = 0.0
    ac_gaps: list[str] = Field(default_factory=list)
    uncertainty: str | None = None
