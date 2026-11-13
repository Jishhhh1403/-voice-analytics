"""Deterministic, leakage-free preprocessing before FAMD."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from .feature_builder import FeatureRow, FeatureSpec


@dataclass
class PreparedFrame:
    frame: pd.DataFrame
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def prepare_frame(
    rows: list[FeatureRow],
    specs: list[FeatureSpec],
    include_missing_indicators: bool = False,
) -> PreparedFrame:
    if not rows:
        return PreparedFrame(frame=pd.DataFrame(), metadata={"rows": 0, "features": 0})

    data: dict[str, list[Any]] = {}
    missing_counts: dict[str, int] = {}
    imputed_counts: dict[str, int] = {}
    transforms: dict[str, str] = {}
    clipping: dict[str, dict[str, float]] = {}
    missing_indicators: list[str] = []
    warnings: list[str] = []

    for spec in specs:
        raw_values = [row.values.get(spec.name) for row in rows]
        if spec.kind == "categorical":
            normalized = [
                str(value).strip() if value is not None and str(value).strip() else None for value in raw_values
            ]
            missing = sum(1 for value in normalized if value is None)
            missing_counts[spec.name] = missing
            if missing:
                imputed_counts[spec.name] = missing
                warnings.append(
                    f"{spec.name} filled {missing} missing values with the explicit __MISSING__ category for fitting."
                )
            data[spec.name] = pd.Series(
                [value if value is not None else "__MISSING__" for value in normalized],
                dtype="object",
            )
            transforms[spec.name] = "missing_category"
            continue

        series = pd.Series([None if value is None else float(value) for value in raw_values], dtype="float64")
        missing_counts[spec.name] = int(series.isna().sum())
        transforms[spec.name] = spec.transform
        if include_missing_indicators and 0 < missing_counts[spec.name] < len(series):
            indicator_name = f"missing_indicator__{spec.name}"
            data[indicator_name] = series.isna().astype("float64")
            missing_indicators.append(indicator_name)
            transforms[indicator_name] = "missing_indicator"

        if spec.transform == "log1p":
            valid = series.dropna()
            if (valid < 0).any():
                warnings.append(f"{spec.name} contains negative values; log1p clamps them to 0.")
            series = series.map(lambda value: value if pd.isna(value) else math.log1p(max(0.0, float(value))))
            transforms[spec.name] = "log1p"
        elif spec.transform == "winsorize":
            valid = series.dropna()
            if not valid.empty:
                lower = float(valid.quantile(0.01))
                upper = float(valid.quantile(0.99))
                if lower != upper:
                    series = series.clip(lower=lower, upper=upper)
                    clipping[spec.name] = {"lower": lower, "upper": upper}
                    transforms[spec.name] = "winsorize_1_99"
                else:
                    transforms[spec.name] = "none"

        median = series.median(skipna=True)
        if pd.isna(median):
            median = 0.0
            warnings.append(f"{spec.name} has no observed values; imputed with 0.0.")
        imputed = int(series.isna().sum())
        if imputed:
            series = series.fillna(float(median))
            imputed_counts[spec.name] = imputed
            warnings.append(f"{spec.name} imputed {imputed} missing values with the median.")
        data[spec.name] = series

    frame = pd.DataFrame(data)
    frame = frame[frame.notna().all(axis=1)]
    frame = frame.reset_index(drop=True)

    dropped_constant: list[str] = []
    for column in list(frame.columns):
        if frame[column].nunique(dropna=False) <= 1:
            dropped_constant.append(column)
            frame = frame.drop(columns=[column])
            warnings.append(f"{column} was dropped because it has no variance across problems.")
    if dropped_constant:
        warnings.append(
            "Constant or fully-missing features were excluded from FAMD fitting: "
            + ", ".join(sorted(dropped_constant))
        )

    remaining = set(frame.columns)
    categorical_features = [
        spec.name for spec in specs if spec.kind == "categorical" and spec.name in remaining
    ]
    numeric_features = [spec.name for spec in specs if spec.kind == "numeric" and spec.name in remaining]
    return PreparedFrame(
        frame=frame,
        metadata={
            "rows": len(frame),
            "features": len(frame.columns),
            "problem_ids": [row.problem_id for row in rows],
            "missing_counts": missing_counts,
            "imputed_counts": imputed_counts,
            "transforms": transforms,
            "winsorize_bounds": clipping,
            "missing_indicators": missing_indicators,
            "dropped_constant_features": dropped_constant,
            "categorical_features": categorical_features,
            "numeric_features": numeric_features,
        },
        warnings=warnings,
    )
