"""LangChain agent for grounded factor narrative serialization.

The agent receives every canonical problem equation for the selected factor run,
the repository banking taxonomy and deterministic factor statistics. It names and
describes every retained factor in one pass. Statistical metrics are merged back
from the computed evidence so the model cannot alter FAMD values.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections import defaultdict
from typing import Any

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import tool

from ....config import Settings
from ....repository import Repository
from .contracts import FactorNarrativeSerializationProposal
from .equation_serializer import FactorEquationSerializer
from .taxonomy_context import BankingTaxonomyContextBuilder

logger = logging.getLogger("bci.factor_narrative")

FACTOR_NARRATIVE_AGENT_VERSION = "factor-narrative-agent-1.1.0"
FACTOR_NARRATIVE_SYSTEM_PROMPT = """You are a senior banking customer-experience analyst using an agentic workflow.
You receive all canonical problem coefficient vectors for one FAMD factor run, exact factor statistics and the
repository banking taxonomy. The problem coefficient array aligns with factor_order; each signed coefficient is
that problem's term in the corresponding factor equation. The full equation text is redundant with these
coefficients and is not repeated in the prompt.

Your task is to name and describe every retained factor in one coherent narrative serialization.
For each factor:
1. Name the underlying customer-experience construct with clear banking/business language.
2. Explain what the factor separates, using positive and negative coefficients, problem titles/statements,
   journey/aspect/symptom context and taxonomy.
3. Ground every claim in the supplied coefficient vectors, problem context and taxonomy.
4. Copy the exact statistical values supplied for problem_count, problem_share_pct, variance, coefficients
   and top feature contributions. Never invent, recalculate or round them differently.
5. Distinguish the factor from every other retained factor.
6. Do not use F1, F2, D1, Dim.1 or any technical identifier as a factor name.
7. Do not infer causality, revenue impact, churn, regulatory risk or facts absent from the evidence.
8. If evidence is ambiguous, say so in the description and lower confidence.
9. The complete compact evidence is already in the user message. Do not call tools; complete the run in one
   model pass.

Return one structured object covering every supplied factor exactly once. Return only the requested schema.
"""


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _round(value: Any, digits: int = 6) -> float | None:
    number = _finite(value)
    return None if number is None else round(number, digits)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _factor_number(item: dict[str, Any], fallback: int) -> str:
    number = item.get("dimension_number") or fallback
    return f"F{number}"


class FactorNarrativeEvidenceBuilder:
    """Build the complete grounded evidence bundle supplied to the agent."""

    def __init__(self, settings: Settings, repo: Repository) -> None:
        self.settings = settings
        self.repo = repo
        self.serializer = FactorEquationSerializer(repo)
        self.taxonomy_builder = BankingTaxonomyContextBuilder(settings, repo)

    def _dimensions(self, run: dict[str, Any]) -> list[dict[str, Any]]:
        diagnostics = run.get("diagnostics") or {}
        dimensions = diagnostics.get("dimensions") or []
        if dimensions:
            return sorted(
                dimensions,
                key=lambda item: (item.get("dimension_number") or 9999, item.get("dimension_id") or ""),
            )
        return [
            {
                "dimension_id": item["dimension_id"],
                "dimension_number": item.get("dimension_number"),
            }
            for item in sorted(
                run.get("definitions") or [],
                key=lambda item: (item.get("dimension_number") or 9999, item.get("dimension_id") or ""),
            )
        ]

    def _coefficient(self, problem: dict[str, Any], dimension_id: str) -> float:
        for item in problem.get("coefficients") or []:
            if item.get("dimension_id") == dimension_id:
                return float(item.get("coefficient") or 0.0)
        return 0.0

    def _features(self, contributions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        total = sum(abs(float(item.get("contribution") or 0.0)) for item in contributions)
        features: list[dict[str, Any]] = []
        for item in contributions:
            contribution = abs(float(item.get("contribution") or 0.0))
            if contribution <= 0:
                continue
            category = item.get("category_level")
            name = str(item.get("variable_name") or "unknown")
            if category:
                name = f"{name}={category}"
            features.append(
                {
                    "feature_name": name,
                    "feature_type": "category" if category else "variable",
                    "contribution_pct": round((contribution / total) * 100, 4) if total else 0.0,
                    "direction_summary": item.get("direction_summary") or "",
                }
            )
        features.sort(key=lambda item: item["contribution_pct"], reverse=True)
        return features[:10]

    def build(self, run_id: str) -> dict[str, Any]:
        run = self.repo.get_dimension_run(run_id)
        if not run:
            raise KeyError(run_id)
        contract = self.serializer.serialize(run_id)
        feedback_run = self.repo.get_run(run.get("feedback_run_id") or "") or {}
        taxonomy = self.taxonomy_builder.build(feedback_run.get("taxonomy_version"))
        dimensions = self._dimensions(run)
        factor_by_dimension = contract.get("factor_by_dimension") or {}
        contributions = self.repo.get_dimension_contributions(run_id)
        contributions_by_dimension: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for contribution in contributions:
            contributions_by_dimension[contribution["dimension_id"]].append(contribution)
        problems = contract.get("problems") or []
        total_problems = len(problems)

        factor_rows: list[dict[str, Any]] = []
        for fallback, dimension in enumerate(dimensions, start=1):
            dimension_id = dimension["dimension_id"]
            factor_id = factor_by_dimension.get(dimension_id) or _factor_number(dimension, fallback)
            values = [self._coefficient(problem, dimension_id) for problem in problems]
            scored = [
                {
                    "problem_id": problem["canonical_problem_id"],
                    "coefficient": _round(value),
                }
                for problem, value in zip(problems, values, strict=False)
                if value != 0.0
            ]
            positive = sorted(
                [item for item in scored if float(item["coefficient"] or 0) > 0],
                key=lambda item: (-float(item["coefficient"] or 0), item["problem_id"]),
            )
            negative = sorted(
                [item for item in scored if float(item["coefficient"] or 0) < 0],
                key=lambda item: (float(item["coefficient"] or 0), item["problem_id"]),
            )
            abs_values = [abs(value) for value in values]
            factor_rows.append(
                {
                    "factor_id": factor_id,
                    "dimension_id": dimension_id,
                    "dimension_number": dimension.get("dimension_number"),
                    "problem_count": len(scored),
                    "problem_share_pct": round((len(scored) / total_problems) * 100, 4) if total_problems else 0.0,
                    "explained_variance_pct": _round(dimension.get("explained_variance"), 4),
                    "cumulative_variance_pct": _round(dimension.get("cumulative_variance"), 4),
                    "eigenvalue": _round(dimension.get("eigenvalue"), 6),
                    "mean_coefficient": round(_mean(values), 6),
                    "mean_abs_coefficient": round(_mean(abs_values), 6),
                    "min_coefficient": round(min(values), 6) if values else 0.0,
                    "max_coefficient": round(max(values), 6) if values else 0.0,
                    "max_abs_coefficient": round(max(abs_values), 6) if abs_values else 0.0,
                    "top_features": self._features(contributions_by_dimension.get(dimension_id, [])),
                    "representative_problem_ids": [
                        item["problem_id"] for item in sorted(
                            scored,
                            key=lambda item: (-abs(float(item["coefficient"] or 0)), item["problem_id"]),
                        )[:20]
                    ],
                    "positive_problem_ids": [item["problem_id"] for item in positive[:20]],
                    "negative_problem_ids": [item["problem_id"] for item in negative[:20]],
                }
            )

        factor_by_dim = {item["dimension_id"]: item["factor_id"] for item in factor_rows}
        compact_problems = []
        for problem in problems:
            coefficients = {
                factor_by_dim.get(item.get("dimension_id")): _round(item.get("coefficient"))
                for item in problem.get("coefficients") or []
                if factor_by_dim.get(item.get("dimension_id"))
            }
            compact_problems.append(
                {
                    "problem_id": problem["canonical_problem_id"],
                    "title": problem.get("title"),
                    "statement": (problem.get("problem_statement") or "")[:500],
                    "journey": problem.get("journey"),
                    "aspect": problem.get("aspect"),
                    "customer_intent": problem.get("customer_intent"),
                    "symptom_category": problem.get("symptom_category"),
                    "transaction_state": problem.get("transaction_state"),
                    "equation": (problem.get("equation_text") or "")[:800],
                    "coefficients": coefficients,
                }
            )

        return {
            "run_id": run_id,
            "feedback_run_id": run.get("feedback_run_id"),
            "taxonomy_version": taxonomy["version"],
            "banking_taxonomy_context": taxonomy,
            "total_problems": total_problems,
            "total_factors": len(factor_rows),
            "coefficient_interpretation": contract.get("coefficient_interpretation"),
            "factors": factor_rows,
            "problems": compact_problems,
        }


def _compact_prompt_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    factor_ids = [item["factor_id"] for item in evidence["factors"]]
    factors: list[dict[str, Any]] = []
    for item in evidence["factors"]:
        compact = dict(item)
        compact.pop("dimension_id", None)
        compact.pop("dimension_number", None)
        compact["top_features"] = (item.get("top_features") or [])[:8]
        for key in ("representative_problem_ids", "positive_problem_ids", "negative_problem_ids"):
            compact[key] = (item.get(key) or [])[:12]
        factors.append(compact)

    problems: list[list[Any]] = []
    for problem in evidence["problems"]:
        journey = problem.get("journey")
        if isinstance(journey, dict):
            journey = journey.get("feature_id") or journey.get("node_id") or journey.get("module_id")
        coefficients = problem.get("coefficients") or {}
        problems.append(
            [
                problem.get("problem_id"),
                problem.get("title"),
                (problem.get("statement") or "")[:320],
                journey,
                problem.get("aspect"),
                problem.get("customer_intent"),
                problem.get("symptom_category"),
                problem.get("transaction_state"),
                [coefficients.get(factor_id) for factor_id in factor_ids],
            ]
        )

    taxonomy = {
        key: value
        for key, value in (evidence.get("banking_taxonomy_context") or {}).items()
        if key != "banking_features"
    }
    return {
        "problem_columns": [
            "problem_id",
            "title",
            "statement",
            "journey",
            "aspect",
            "customer_intent",
            "symptom_category",
            "transaction_state",
            "coefficients",
        ],
        "factor_order": factor_ids,
        "coefficient_note": (
            "Each problem's coefficients array aligns with factor_order; each signed value is that "
            "problem's coefficient in the corresponding factor equation."
        ),
        "factors": factors,
        "problems": problems,
        "banking_taxonomy_context": taxonomy,
    }


def _extract_structured(result: Any) -> dict[str, Any]:
    structured = result.get("structured_response") if isinstance(result, dict) else None
    if structured is None and isinstance(result, dict):
        structured = result.get("output")
    if structured is None:
        raise ValueError("The LangChain agent returned no structured response.")
    if hasattr(structured, "model_dump"):
        return structured.model_dump()
    if isinstance(structured, dict):
        return structured
    raise ValueError("The LangChain agent returned an unsupported structured response.")


def _model_id(model: BaseChatModel) -> str:
    return str(getattr(model, "model_name", None) or getattr(model, "model", None) or model.__class__.__name__)


_QUOTA_MARKERS = (
    "resource_exhausted",
    "429",
    "quota exceeded",
    "quota has been exceeded",
    "rate limit",
)
_TRANSIENT_MARKERS = (
    "unexpected_eof",
    "unexpected eof",
    "eof while reading",
    "ssl",
    "connection reset",
    "connection aborted",
    "connection refused",
    "connection error",
    "timed out",
    "timeout",
    "temporarily unavailable",
    "service unavailable",
    "bad gateway",
    " 500",
    " 502",
    " 503",
    " 504",
)
_INVALID_OUTPUT_MARKERS = (
    "validation",
    "coverage mismatch",
    "structured response",
    "invalid technical factor name",
    "field required",
)


def _error_kind(exc: Exception) -> str:
    message = str(exc).casefold()
    if any(marker in message for marker in _QUOTA_MARKERS):
        return "quota"
    if any(marker in message for marker in _TRANSIENT_MARKERS):
        return "transient"
    if any(marker in message for marker in _INVALID_OUTPUT_MARKERS):
        return "invalid"
    return "other"


def _friendly_error(model: str, exc: Exception, attempts: int) -> str:
    kind = _error_kind(exc)
    if kind == "quota":
        retry_hint = re.search(r"please retry in ([^\.]+)", str(exc), flags=re.IGNORECASE)
        suffix = f" Retry after {retry_hint.group(1).strip()}." if retry_hint else ""
        return (
            f"{model} quota is exhausted. Check the provider plan or configure a fallback provider."
            f"{suffix}"
        )
    if kind == "transient":
        return (
            f"{model} closed the connection before completing the factor narrative after "
            f"{attempts} attempt(s). Check network/proxy connectivity and retry."
        )
    if kind == "invalid":
        return (
            f"{model} returned an incomplete or invalid factor narrative after {attempts} attempt(s). "
            "Retry the agent; no factors were changed."
        )
    return f"{model} failed after {attempts} attempt(s): {str(exc)[:500]}"


def build_chat_models(settings: Settings) -> list[BaseChatModel]:
    if not settings.problem_dimension_llm_enabled:
        return []
    names = [settings.problem_dimension_llm_provider]
    fallback = (settings.problem_dimension_llm_fallback_provider or "").strip()
    if fallback and fallback.casefold() != settings.problem_dimension_llm_provider.casefold():
        names.append(fallback)
    models: list[BaseChatModel] = []
    for name in names:
        provider = (name or "").strip().casefold().replace("-", "_")
        if provider == "auto":
            provider = "gemini" if settings.gemini_api_key else "openai_compatible"
        if provider in {"gemini", "google"} and settings.gemini_api_key:
            from langchain_google_genai import ChatGoogleGenerativeAI

            primary = settings.problem_dimension_llm_model or settings.gemini_model or settings.llm_model
            model_names = [primary]
            for fallback_model in settings.problem_dimension_factor_narrative_model_fallbacks.split(","):
                name = fallback_model.strip()
                if name and name not in model_names:
                    model_names.append(name)
            for model_name in model_names:
                models.append(
                    ChatGoogleGenerativeAI(
                        model=model_name,
                        api_key=settings.gemini_api_key,
                        temperature=settings.problem_dimension_llm_temperature,
                        max_tokens=settings.problem_dimension_factor_narrative_max_output_tokens,
                        request_timeout=settings.problem_dimension_factor_narrative_timeout_seconds,
                        retries=0,
                    )
                )
        elif provider in {"openai", "openai_compatible", "ollama", "local", "vllm"}:
            from langchain_openai import ChatOpenAI

            models.append(
                ChatOpenAI(
                    model=settings.problem_dimension_llm_model or settings.openai_model,
                    base_url=settings.problem_dimension_llm_base_url or settings.openai_base_url,
                    api_key=settings.problem_dimension_llm_api_key or settings.openai_api_key or "local",
                    temperature=settings.problem_dimension_llm_temperature,
                    max_completion_tokens=settings.problem_dimension_factor_narrative_max_output_tokens,
                    timeout=settings.problem_dimension_factor_narrative_timeout_seconds,
                    max_retries=0,
                )
            )
    return models


class FactorNarrativeAgent:
    """Run a LangChain tool-using agent over all problem equations and taxonomy."""

    def __init__(
        self,
        settings: Settings,
        repo: Repository,
        models: list[BaseChatModel] | None = None,
    ) -> None:
        self.settings = settings
        self.repo = repo
        self.models = models if models is not None else build_chat_models(settings)
        self.evidence_builder = FactorNarrativeEvidenceBuilder(settings, repo)

    @property
    def available(self) -> bool:
        return bool(self.models)

    def _tools(self, evidence: dict[str, Any]) -> list[Any]:
        factors = {item["factor_id"]: item for item in evidence["factors"]}
        problems = evidence["problems"]
        taxonomy = evidence["banking_taxonomy_context"]

        @tool
        def factor_statistics(factor_id: str) -> str:
            """Return exact statistics and top features for one factor ID such as F1."""
            item = factors.get(factor_id)
            if not item:
                return json.dumps({"error": f"Unknown factor_id {factor_id}"})
            return json.dumps(item, ensure_ascii=False, sort_keys=True)

        @tool
        def problem_equations(
            factor_id: str,
            direction: str = "all",
            limit: int = 121,
            offset: int = 0,
        ) -> str:
            """Return canonical problem equations sorted by strongest absolute coefficient for one factor."""
            if factor_id not in factors:
                return json.dumps({"error": f"Unknown factor_id {factor_id}"})
            normalized = (direction or "all").casefold()
            rows = []
            for problem in problems:
                coefficient = problem["coefficients"].get(factor_id)
                if coefficient is None:
                    continue
                if normalized == "positive" and coefficient <= 0:
                    continue
                if normalized == "negative" and coefficient >= 0:
                    continue
                rows.append(
                    {
                        "problem_id": problem["problem_id"],
                        "title": problem["title"],
                        "statement": problem["statement"],
                        "journey": problem["journey"],
                        "aspect": problem["aspect"],
                        "symptom_category": problem["symptom_category"],
                        "coefficient": coefficient,
                        "equation": problem["equation"],
                    }
                )
            rows.sort(key=lambda item: (-abs(float(item["coefficient"])), item["problem_id"]))
            safe_limit = max(1, min(limit, 500))
            safe_offset = max(0, offset)
            return json.dumps(
                {
                    "factor_id": factor_id,
                    "total_problems": len(rows),
                    "offset": safe_offset,
                    "problems": rows[safe_offset : safe_offset + safe_limit],
                },
                ensure_ascii=False,
                sort_keys=True,
            )

        @tool
        def taxonomy_context() -> str:
            """Return the repository banking taxonomy, journey fields, process knowledge and caveats."""
            return json.dumps(taxonomy, ensure_ascii=False, sort_keys=True)

        return [factor_statistics, problem_equations, taxonomy_context]

    def _ground(self, proposal: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
        computed = {item["factor_id"]: item for item in evidence["factors"]}
        known_problem_ids = {item["problem_id"] for item in evidence["problems"]}
        submitted = proposal.get("factors") or []
        by_id = {item.get("factor_id"): item for item in submitted if isinstance(item, dict)}
        missing = sorted(set(computed) - set(by_id))
        extra = sorted(set(by_id) - set(computed))
        if missing or extra:
            raise ValueError(f"Agent factor coverage mismatch; missing={missing}, extra={extra}")
        grounded: list[dict[str, Any]] = []
        for factor_id, stats in computed.items():
            item = dict(by_id[factor_id])
            name = str(item.get("name") or "").strip()
            short_name = str(item.get("short_name") or "").strip()
            if (
                not name
                or not short_name
                or re.search(r"\b[FD]\d+\b", f"{name} {short_name}", flags=re.IGNORECASE)
            ):
                raise ValueError(f"Agent returned an invalid technical factor name for {factor_id}: {name!r}")
            item["name"] = name
            item["short_name"] = short_name
            item["factor_id"] = factor_id
            item["dimension_id"] = stats["dimension_id"]
            for key in (
                "problem_count",
                "problem_share_pct",
                "explained_variance_pct",
                "cumulative_variance_pct",
                "mean_coefficient",
                "mean_abs_coefficient",
                "min_coefficient",
                "max_coefficient",
                "max_abs_coefficient",
                "top_features",
            ):
                item[key] = stats[key]
            item["representative_problem_ids"] = [
                problem_id
                for problem_id in item.get("representative_problem_ids") or []
                if problem_id in known_problem_ids
            ][:20] or stats["representative_problem_ids"][:20]
            grounded.append(item)
        grounded.sort(key=lambda item: int(item["factor_id"].removeprefix("F")))
        return {
            "status": "COMPLETED",
            "summary": proposal.get("summary"),
            "factors": grounded,
            "taxonomy_version": evidence["taxonomy_version"],
            "total_problems": evidence["total_problems"],
            "total_factors": evidence["total_factors"],
        }

    def generate(self, run_id: str) -> dict[str, Any]:
        if not self.available:
            return {
                "status": "UNAVAILABLE",
                "reason": "No LangChain chat model is configured for factor narrative serialization.",
                "factors": [],
            }
        evidence = self.evidence_builder.build(run_id)
        tools = self._tools(evidence)
        prompt = json.dumps(
            {
                "prompt_version": self.settings.problem_dimension_factor_narrative_prompt_version,
                "agent_version": FACTOR_NARRATIVE_AGENT_VERSION,
                "total_problems": evidence["total_problems"],
                "total_factors": evidence["total_factors"],
                "taxonomy_version": evidence["taxonomy_version"],
                "coefficient_interpretation": evidence["coefficient_interpretation"],
                **_compact_prompt_evidence(evidence),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        errors: list[str] = []
        retries = max(0, self.settings.problem_dimension_factor_narrative_retry_attempts)
        failed_models: set[int] = set()
        attempts_by_model: dict[int, int] = defaultdict(int)
        for attempt in range(retries + 1):
            for index, model in enumerate(self.models):
                if index in failed_models:
                    continue
                model_name = _model_id(model)
                attempts_by_model[index] += 1
                try:
                    agent = create_agent(
                        model=model,
                        tools=tools,
                        system_prompt=FACTOR_NARRATIVE_SYSTEM_PROMPT,
                        response_format=ToolStrategy(FactorNarrativeSerializationProposal),
                        name="factor_narrative_agent",
                    )
                    result = agent.invoke(
                        {"messages": [{"role": "user", "content": prompt}]},
                        config={"recursion_limit": 80},
                    )
                    proposal = FactorNarrativeSerializationProposal.model_validate(
                        _extract_structured(result)
                    ).model_dump()
                    grounded = self._ground(proposal, evidence)
                    grounded["model_name"] = model_name
                    grounded["prompt_version"] = self.settings.problem_dimension_factor_narrative_prompt_version
                    grounded["agent_version"] = FACTOR_NARRATIVE_AGENT_VERSION
                    return grounded
                except Exception as exc:
                    kind = _error_kind(exc)
                    model_attempts = attempts_by_model[index]
                    logger.warning(
                        "factor narrative agent failed model=%s run=%s attempt=%s kind=%s error=%s",
                        model_name,
                        run_id,
                        model_attempts,
                        kind,
                        exc,
                    )
                    retryable = kind in {"transient", "invalid"}
                    if retryable and attempt < retries:
                        continue
                    errors.append(_friendly_error(model_name, exc, model_attempts))
                    failed_models.add(index)
            if len(failed_models) >= len(self.models):
                break
            if attempt < retries:
                time.sleep(min(2**attempt, 8))
        return {
            "status": "FAILED",
            "reason": "; ".join(errors) or "Factor narrative agent failed.",
            "factors": [],
        }
