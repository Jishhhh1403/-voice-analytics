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
    synthetic_customer_ref: str | None = None
    rating: int | None = None
    feedback_title: str = ""
    feedback_text_redacted: str
    content_fingerprint: str
    is_synthetic: bool = True


class ExtractedInsight(BaseModel):
    insight_id: str
    feedback_id: str
    sentence_index: int
    customer_intent: str | None = None
    aspect: str | None = None
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
    language: str = "en"
    model_id: str = "rules-v1"
    prompt_version: str = "rules-1.0"
    schema_version: str = "1.0.0"
    extraction_timestamp: str
    extraction_method: str = "rules"
    confidence: float = 0.5
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
    customer_intent: str | None = None
    aspect: str | None = None
    symptom_category: str | None = None
    journey_node_id: str | None = None
    evidence_count: int = 0
    distinct_customers: int = 0
    negative_count: int = 0
    first_seen: str | None = None
    last_seen: str | None = None
    cluster_id: str | None = None
    lifecycle_status: str = "candidate"


class BacklogProfile(BaseModel):
    backlog_id: str
    title: str
    description: str
    acceptance_criteria: str = ""
    product_area: str | None = None
    priority: str | None = None
    business_goal: str | None = None
    intents: list[str] = Field(default_factory=list)
    aspects: list[str] = Field(default_factory=list)
    journey_node_id: str | None = None
    covered_symptoms: list[str] = Field(default_factory=list)
    tokens: list[str] = Field(default_factory=list)


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
