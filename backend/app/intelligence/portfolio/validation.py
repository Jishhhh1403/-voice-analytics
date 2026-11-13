"""Deterministic validation of model-generated portfolio narratives."""

from __future__ import annotations

import re
from typing import Any

from .contracts import PortfolioNarrative

TECHNICAL_ID_PATTERN = re.compile(r"\b(?:F\d+|D\d+|CP-[A-Za-z0-9-]{6,})\b")
FACTOR_LABEL_PATTERN = re.compile(r"\bfactor\s+\d+\b", re.IGNORECASE)
CAUSAL_PATTERN = re.compile(
    r"\b(?:causes?|caused by|drives?|driven by|leads? to|results? in|responsible for)\b",
    re.IGNORECASE,
)
MDS_AXIS_PATTERN = re.compile(
    r"\b(?:mds\s+)?(?:x|y)[- ]axis\b|\b(?:mds\s+)?(?:axis|dimension)\s*[12]\b",
    re.IGNORECASE,
)
INTERPRETIVE_PATTERN = re.compile(r"\b(?:means?|represents?|indicates?|shows?)\b", re.IGNORECASE)
CAUSAL_SHARE_PATTERN = re.compile(
    r"\b(?:cause|causal|drive|explain|account(?:s|ed|ing)? for|responsible|impact)\w*\b",
    re.IGNORECASE,
)
ZERO_PATTERN = re.compile(r"\b(?:zero|0|none)\b", re.IGNORECASE)


def _check(name: str, passed: bool, message: str, *, warning: bool = False) -> dict[str, Any]:
    return {
        "name": name,
        "status": "PASS" if passed else ("WARN" if warning else "FAIL"),
        "message": message,
    }


def _prose_blocks(narrative: PortfolioNarrative) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = [
        ("title", narrative.title),
        ("executive_summary", narrative.executive_summary),
        *[(f"data_limitations[{index}]", value) for index, value in enumerate(narrative.data_limitations)],
        *[(f"methodology_notes[{index}]", value) for index, value in enumerate(narrative.methodology_notes)],
    ]
    for index, finding in enumerate(narrative.key_findings):
        blocks.extend(
            [
                (f"key_findings[{index}].title", finding.title),
                (f"key_findings[{index}].narrative", finding.narrative),
                (f"key_findings[{index}].business_implication", finding.business_implication),
                *[
                    (f"key_findings[{index}].limitations[{item_index}]", value)
                    for item_index, value in enumerate(finding.limitations)
                ],
            ]
        )
    for index, factor in enumerate(narrative.factor_interpretations):
        blocks.extend(
            [
                (f"factor_interpretations[{index}].factor_name", factor.factor_name),
                (f"factor_interpretations[{index}].interpretation", factor.interpretation),
                (f"factor_interpretations[{index}].business_implication", factor.business_implication),
                *[
                    (f"factor_interpretations[{index}].common_problem_patterns[{item_index}]", value)
                    for item_index, value in enumerate(factor.common_problem_patterns)
                ],
                *[
                    (f"factor_interpretations[{index}].limitations[{item_index}]", value)
                    for item_index, value in enumerate(factor.limitations)
                ],
            ]
        )
    for index, action in enumerate(narrative.recommended_actions):
        blocks.extend(
            [
                (f"recommended_actions[{index}].action", action.action),
                (f"recommended_actions[{index}].rationale", action.rationale),
                *[
                    (f"recommended_actions[{index}].limitations[{item_index}]", value)
                    for item_index, value in enumerate(action.limitations)
                ],
            ]
        )
    return blocks


def _sentences(text: str) -> list[str]:
    return [item.strip() for item in re.split(r"(?<=[.!?])\s+", text) if item.strip()]


def validate_portfolio_narrative(
    narrative: PortfolioNarrative,
    serialization: dict[str, Any],
) -> dict[str, Any]:
    """Validate structure, grounding, terminology and interpretation safety."""

    checks: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []

    nomenclature = serialization.get("factor_nomenclature") or []
    problems = serialization.get("problems") or []
    known_names = {str(item["business_name"]): item for item in nomenclature if item.get("business_name")}
    known_names_folded = {name.casefold(): name for name in known_names}
    known_problem_ids = {str(item["problem_id"]) for item in problems}
    provisional_names = {
        str(item["business_name"])
        for item in nomenclature
        if item.get("provisional") and item.get("business_name")
    }
    metric_names = set((serialization.get("data_quality") or {}).get("measurement_metrics") or [])

    blocks = _prose_blocks(narrative)

    technical_hits = [
        f"{path}: {match.group(0)}"
        for path, text in blocks
        for match in TECHNICAL_ID_PATTERN.finditer(text)
    ]
    checks.append(
        _check(
            "no_technical_factor_ids",
            not technical_hits,
            "No technical factor or dimension identifiers appear in narrative prose."
            if not technical_hits
            else "Technical identifiers found in prose: " + "; ".join(technical_hits[:10]),
        )
    )
    if technical_hits:
        errors.append("Narrative prose contains technical factor or problem identifiers.")

    factor_label_hits = [
        f"{path}: {match.group(0)}"
        for path, text in blocks
        for match in FACTOR_LABEL_PATTERN.finditer(text)
    ]
    checks.append(
        _check(
            "business_factor_names",
            not factor_label_hits,
            "Factor references use business names." if not factor_label_hits else "Generic factor labels found: " + "; ".join(factor_label_hits[:10]),
        )
    )
    if factor_label_hits:
        errors.append("Narrative uses generic factor labels instead of approved business names.")

    causal_hits = [
        f"{path}: {match.group(0)}"
        for path, text in blocks
        for match in CAUSAL_PATTERN.finditer(text)
    ]
    checks.append(
        _check(
            "no_causal_language",
            not causal_hits,
            "No causal verbs were detected." if not causal_hits else "Causal language found: " + "; ".join(causal_hits[:10]),
        )
    )
    if causal_hits:
        errors.append("Narrative makes causal claims; coefficients are associations only.")

    axis_hits = []
    for path, text in blocks:
        if MDS_AXIS_PATTERN.search(text) and INTERPRETIVE_PATTERN.search(text):
            axis_hits.append(path)
    checks.append(
        _check(
            "mds_axes_not_interpreted",
            not axis_hits,
            "MDS axes are not assigned business meaning." if not axis_hits else "MDS axis interpretation found in: " + ", ".join(axis_hits[:10]),
        )
    )
    if axis_hits:
        errors.append("Narrative assigns business meaning to MDS axes or dimensions.")

    causal_share_hits = []
    for path, text in blocks:
        for sentence in _sentences(text):
            lowered = sentence.casefold()
            if "share" not in lowered and "percent" not in lowered and "%" not in lowered:
                continue
            if not CAUSAL_SHARE_PATTERN.search(sentence):
                continue
            if re.search(r"\b(?:not|no|never|neither)\b", lowered):
                continue
            causal_share_hits.append(f"{path}: {sentence}")
    checks.append(
        _check(
            "relative_share_not_causal",
            not causal_share_hits,
            "Relative shares are not described as causal contributions."
            if not causal_share_hits
            else "Causal share language found: " + "; ".join(causal_share_hits[:5]),
        )
    )
    if causal_share_hits:
        errors.append("Narrative treats relative squared-coordinate shares as causal contributions.")

    bad_factor_names = []
    for index, factor in enumerate(narrative.factor_interpretations):
        if factor.factor_name not in known_names:
            bad_factor_names.append(f"factor_interpretations[{index}]: {factor.factor_name}")
    checks.append(
        _check(
            "factor_names_grounded",
            not bad_factor_names,
            "Every interpreted factor uses an approved business name."
            if not bad_factor_names
            else "Unknown factor names: " + "; ".join(bad_factor_names[:10]),
        )
    )
    if bad_factor_names:
        errors.append("Narrative interprets factor names that are not in the approved nomenclature.")

    bad_problem_refs: list[str] = []
    bad_factor_refs: list[str] = []
    bad_metric_refs: list[str] = []
    for path, refs in _evidence_blocks(narrative):
        for index, ref in enumerate(refs):
            if ref.problem_id and ref.problem_id not in known_problem_ids:
                bad_problem_refs.append(f"{path}[{index}]: {ref.problem_id}")
            if ref.factor_name and ref.factor_name not in known_names and ref.factor_name.casefold() not in known_names_folded:
                bad_factor_refs.append(f"{path}[{index}]: {ref.factor_name}")
            if ref.metric_name and metric_names and ref.metric_name not in metric_names:
                bad_metric_refs.append(f"{path}[{index}]: {ref.metric_name}")
    checks.append(
        _check(
            "evidence_problem_refs",
            not bad_problem_refs,
            "All evidence problem references exist in the serialization."
            if not bad_problem_refs
            else "Unknown problem references: " + "; ".join(bad_problem_refs[:10]),
        )
    )
    if bad_problem_refs:
        errors.append("Narrative cites problem references that are not in the serialization.")
    checks.append(
        _check(
            "evidence_factor_refs",
            not bad_factor_refs,
            "All evidence factor references use known business names."
            if not bad_factor_refs
            else "Unknown factor references: " + "; ".join(bad_factor_refs[:10]),
        )
    )
    if bad_factor_refs:
        errors.append("Narrative cites factor names that are not in the approved nomenclature.")
    checks.append(
        _check(
            "evidence_metric_refs",
            not bad_metric_refs,
            "All evidence metric references are known."
            if not bad_metric_refs
            else "Unknown metric references: " + "; ".join(bad_metric_refs[:10]),
            warning=True,
        )
    )
    if bad_metric_refs:
        warnings.append("Narrative cites metric names that are not in the serialized metric set.")

    if provisional_names:
        qualification_text = " ".join(
            [
                narrative.executive_summary,
                *narrative.data_limitations,
                *narrative.methodology_notes,
                *[value for factor in narrative.factor_interpretations for value in factor.limitations],
            ]
        ).casefold()
        qualified = any(token in qualification_text for token in ("provisional", "draft", "requires review", "require review"))
        checks.append(
            _check(
                "provisional_factors_qualified",
                qualified,
                "Provisional factors are clearly qualified." if qualified else "Provisional factors are not qualified as draft or requiring review.",
            )
        )
        if not qualified:
            errors.append("Provisional factor names are presented without a draft/review qualification.")

    missing_metric_zero_hits = []
    missing_metrics = (serialization.get("portfolio_summary") or {}).get("missing_measurement_counts") or {}
    for path, text in blocks:
        for metric_name in missing_metrics:
            label = metric_name.replace("_", " ")
            if ZERO_PATTERN.search(text) and label.casefold() in text.casefold():
                missing_metric_zero_hits.append(f"{path}: {metric_name}")
    checks.append(
        _check(
            "missing_values_not_zero",
            not missing_metric_zero_hits,
            "No missing metric was described as zero." if not missing_metric_zero_hits else "Possible missing-as-zero language: " + "; ".join(missing_metric_zero_hits[:5]),
            warning=True,
        )
    )
    if missing_metric_zero_hits:
        warnings.append("Narrative may describe a missing measurement as zero.")

    missing_factor_interpretations = sorted(set(known_names) - {item.factor_name for item in narrative.factor_interpretations})
    checks.append(
        _check(
            "factor_coverage",
            not missing_factor_interpretations,
            "Every approved factor is interpreted."
            if not missing_factor_interpretations
            else "Factors not interpreted: " + ", ".join(missing_factor_interpretations[:10]),
            warning=True,
        )
    )
    if missing_factor_interpretations:
        warnings.append("Narrative does not interpret every approved factor.")

    if not narrative.key_findings:
        errors.append("Narrative contains no key findings.")
    if not narrative.recommended_actions:
        errors.append("Narrative contains no recommended actions.")

    status = "FAILED" if errors else ("WARNING" if warnings else "PASSED")
    return {
        "status": status,
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
    }


def _evidence_blocks(narrative: PortfolioNarrative) -> list[tuple[str, list[Any]]]:
    blocks: list[tuple[str, list[Any]]] = []
    for index, finding in enumerate(narrative.key_findings):
        blocks.append((f"key_findings[{index}].evidence", finding.evidence))
    for index, factor in enumerate(narrative.factor_interpretations):
        blocks.append((f"factor_interpretations[{index}].evidence", factor.evidence))
    for index, action in enumerate(narrative.recommended_actions):
        blocks.append((f"recommended_actions[{index}].evidence", action.evidence))
    return blocks
