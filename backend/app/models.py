from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class FeedbackPipelineRequest(BaseModel):
    input_uri: str | None = Field(default=None, description="local:// or gs:// object URI; defaults to seeded sample")
    object_generation: str | None = None
    tenant_id: str | None = None
    force_rerun: bool = False


class PipelineStartResponse(BaseModel):
    run_id: str
    status: str = "queued"
    correlation_id: str


class StageStatus(BaseModel):
    stage: str
    status: str
    started_at: str | None = None
    finished_at: str | None = None
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    message: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)


class PipelineRunOut(BaseModel):
    run_id: str
    tenant_id: str
    run_type: str
    status: str
    input_uri: str | None = None
    input_generation: str | None = None
    source_filename: str | None = None
    code_version: str | None = None
    schema_version: str | None = None
    model_version: str | None = None
    taxonomy_version: str | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    correlation_id: str | None = None
    error: str | None = None
    summary: dict[str, Any] = Field(default_factory=dict)
    stages: list[StageStatus] = Field(default_factory=list)


class ProblemReviewRequest(BaseModel):
    reviewer: str = Field(min_length=1, max_length=120)
    decision: Literal["accept", "reject", "merge", "split", "rename", "mark_in_review", "deprecate"]
    note: str = Field(default="", max_length=2000)
    target_problem_id: str | None = None
    new_title: str | None = None


class TaxonomyDecisionRequest(BaseModel):
    reviewer: str = Field(min_length=1, max_length=120)
    decision: Literal["approve", "reject"]
    note: str = Field(default="", max_length=2000)


class ReportReviewRequest(BaseModel):
    reviewer: str = Field(min_length=1, max_length=120)
    decision: Literal["accept_recommendation", "disagree", "further_investigation"]
    note: str = Field(default="", max_length=2000)
    backlog_id: str | None = None


class ValidateBacklogRequest(BaseModel):
    force_rerun: bool = False


class MessageResponse(BaseModel):
    message: str
