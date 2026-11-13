"""Data-quality gates for the dimension feature matrix."""

from __future__ import annotations

from collections import Counter
from typing import Any

from .feature_builder import FORBIDDEN_FEATURES, FeatureRow, FeatureSpec

CRITICAL = "CRITICAL"
WARNING = "WARNING"

PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"


def _check(
    name: str,
    status: str,
    severity: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "severity": severity,
        "message": message,
        "details": details or {},
    }


def run_quality_checks(
    rows: list[FeatureRow],
    specs: list[FeatureSpec],
    min_problems: int = 30,
    min_category_count: int = 2,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    row_count = len(rows)
    checks.append(
        _check(
            "row_count",
            PASS if row_count >= min_problems else FAIL,
            CRITICAL,
            f"{row_count} canonical problems available; minimum is {min_problems}.",
            {"row_count": row_count, "minimum": min_problems},
        )
    )

    duplicate_ids = sorted(pid for pid, count in Counter(row.problem_id for row in rows).items() if count > 1)
    checks.append(
        _check(
            "duplicate_problem_ids",
            PASS if not duplicate_ids else FAIL,
            CRITICAL,
            "Every canonical problem appears exactly once." if not duplicate_ids else "Duplicate canonical problems found.",
            {"duplicate_ids": duplicate_ids[:20], "count": len(duplicate_ids)},
        )
    )

    leaked = sorted(
        {
            name
            for row in rows
            for name in row.values
            if name.lower() in FORBIDDEN_FEATURES
        }
        | {spec.name for spec in specs if spec.name.lower() in FORBIDDEN_FEATURES}
    )
    checks.append(
        _check(
            "forbidden_features",
            PASS if not leaked else FAIL,
            CRITICAL,
            "No identifiers, free text, MDS coordinates or priority scores are active features."
            if not leaked
            else "Forbidden fields leaked into the feature matrix.",
            {"features": leaked},
        )
    )

    feature_names = [spec.name for spec in specs]
    for spec in specs:
        missing = sum(1 for row in rows if row.values.get(spec.name) is None)
        missing_share = missing / row_count if row_count else 1.0
        if leaks := (spec.name in FORBIDDEN_FEATURES):
            status = FAIL
        elif missing == row_count or missing_share > 0.5:
            status = WARN
        else:
            status = PASS
        checks.append(
            _check(
                f"missingness:{spec.name}",
                status,
                CRITICAL if status == FAIL else WARNING,
                f"{missing}/{row_count} rows missing {spec.name}.",
                {
                    "feature": spec.name,
                    "missing_count": missing,
                    "missing_share": round(missing_share, 4),
                    "forbidden": bool(leaks),
                },
            )
        )

    for spec in specs:
        if spec.kind != "categorical":
            continue
        observed = [str(row.values[spec.name]) for row in rows if row.values.get(spec.name) is not None]
        counts = Counter(observed)
        rare = {level: count for level, count in counts.items() if count < min_category_count}
        if not counts:
            status = WARN
            message = f"{spec.name} has no observed levels."
        elif len(counts) <= 1:
            status = WARN
            message = f"{spec.name} has only one observed level."
        elif rare:
            status = WARN
            message = f"{spec.name} includes levels with fewer than {min_category_count} problems."
        else:
            status = PASS
            message = f"{spec.name} has {len(counts)} usable levels."
        checks.append(
            _check(
                f"category_sparsity:{spec.name}",
                status,
                WARNING,
                message,
                {"levels": dict(counts), "rare_levels": rare, "minimum_count": min_category_count},
            )
        )

    for spec in specs:
        if spec.kind != "numeric":
            continue
        values = [float(row.values[spec.name]) for row in rows if row.values.get(spec.name) is not None]
        unique = len(set(values))
        if not values:
            status = WARN
            message = f"{spec.name} has no numeric values and will be excluded from fitting."
        elif unique <= 1:
            status = WARN
            message = f"{spec.name} has no variance across problems."
        else:
            status = PASS
            message = f"{spec.name} has {unique} distinct values."
        checks.append(
            _check(
                f"variance:{spec.name}",
                status,
                CRITICAL if status == FAIL else WARNING,
                message,
                {"feature": spec.name, "non_missing": len(values), "distinct": unique},
            )
        )

    numeric_specs = [spec.name for spec in specs if spec.kind == "numeric"]
    seen: dict[tuple[float, ...], str] = {}
    duplicates: list[dict[str, str]] = []
    for name in numeric_specs:
        vector = tuple(round(float(row.values[name]), 8) for row in rows if row.values.get(name) is not None)
        if len(vector) != row_count or not vector:
            continue
        if vector in seen:
            duplicates.append({"feature": name, "duplicate_of": seen[vector]})
        else:
            seen[vector] = name
    checks.append(
        _check(
            "duplicate_numeric_features",
            PASS if not duplicates else WARN,
            WARNING,
            "No identical numeric feature vectors." if not duplicates else "Identical numeric feature vectors found.",
            {"duplicates": duplicates},
        )
    )

    denominator_warnings: list[dict[str, Any]] = []
    for row in rows:
        for feature, denominator in row.denominators.items():
            if denominator is not None and denominator <= 0 and row.values.get(feature) is not None:
                denominator_warnings.append({"problem_id": row.problem_id, "feature": feature})
    checks.append(
        _check(
            "rate_denominators",
            PASS if not denominator_warnings else WARN,
            WARNING,
            "Rate features have valid denominators or remain missing."
            if not denominator_warnings
            else "Some rate features have non-positive denominators.",
            {"problems": denominator_warnings[:50], "count": len(denominator_warnings)},
        )
    )

    checks.append(
        _check(
            "available_features",
            PASS if feature_names else FAIL,
            CRITICAL,
            f"{len(feature_names)} versioned features configured.",
            {"features": feature_names},
        )
    )
    return checks


def has_critical_failure(checks: list[dict[str, Any]]) -> bool:
    return any(check["severity"] == CRITICAL and check["status"] == FAIL for check in checks)
