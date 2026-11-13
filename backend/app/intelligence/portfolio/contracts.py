"""Structured narrative contracts returned by the narrative model."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Confidence = Literal["high", "medium", "low"]
ActionHorizon = Literal["now", "next", "later"]


class EvidenceReference(BaseModel):
    """Traceability pointer. Identifiers are allowed here, not in prose."""

    model_config = ConfigDict(extra="forbid")

    problem_id: str | None = None
    factor_name: str | None = None
    metric_name: str | None = None
    note: str | None = Field(default=None, max_length=500)


class NarrativeFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    narrative: str = Field(min_length=1, max_length=4000)
    business_implication: str = Field(min_length=1, max_length=2000)
    confidence: Confidence
    evidence: list[EvidenceReference] = Field(min_length=1)
    limitations: list[str] = Field(default_factory=list, max_length=10)


class FactorInterpretation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    factor_name: str = Field(min_length=1, max_length=200)
    interpretation: str = Field(min_length=1, max_length=4000)
    common_problem_patterns: list[str] = Field(default_factory=list, max_length=10)
    business_implication: str = Field(min_length=1, max_length=2000)
    confidence: Confidence
    evidence: list[EvidenceReference] = Field(min_length=1)
    limitations: list[str] = Field(default_factory=list, max_length=10)


class PortfolioAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str = Field(min_length=1, max_length=1000)
    rationale: str = Field(min_length=1, max_length=2000)
    horizon: ActionHorizon
    evidence: list[EvidenceReference] = Field(min_length=1)
    limitations: list[str] = Field(default_factory=list, max_length=10)


class PortfolioNarrative(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    executive_summary: str = Field(min_length=1, max_length=6000)
    key_findings: list[NarrativeFinding] = Field(min_length=1, max_length=12)
    factor_interpretations: list[FactorInterpretation] = Field(default_factory=list, max_length=30)
    recommended_actions: list[PortfolioAction] = Field(min_length=1, max_length=12)
    data_limitations: list[str] = Field(default_factory=list, max_length=20)
    methodology_notes: list[str] = Field(default_factory=list, max_length=20)
