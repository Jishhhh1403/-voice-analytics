"""Optional exploratory factor analysis on the numeric feature subset.

EFA is a robustness aid only. It does not create publishable dimensions and is
never mixed into the FAMD row scores.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .feature_builder import FeatureSpec
from .preprocessing import PreparedFrame


@dataclass
class EFAResult:
    status: str
    error: str | None = None
    n_factors: int = 0
    features: list[str] = field(default_factory=list)
    factors: list[dict[str, Any]] = field(default_factory=list)
    uniqueness: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "error": self.error,
            "n_factors": self.n_factors,
            "features": self.features,
            "factors": self.factors,
            "uniqueness": self.uniqueness,
            "note": (
                "EFA is an optional robustness check over numeric features only. "
                "It is not used for problem scoring or publication."
            ),
        }


def run_efa(
    prepared: PreparedFrame,
    specs: list[FeatureSpec],
    max_factors: int = 5,
    random_state: int = 42,
) -> EFAResult:
    numeric = [
        name
        for name in prepared.metadata.get("numeric_features", [])
        if name in prepared.frame.columns
    ]
    if not numeric:
        numeric = [
            spec.name
            for spec in specs
            if spec.kind == "numeric" and spec.name in prepared.frame.columns
        ]
    frame = prepared.frame[numeric] if numeric else prepared.frame.iloc[:, :0]
    if frame.empty or frame.shape[0] < 5 or frame.shape[1] < 3:
        return EFAResult(
            status="INSUFFICIENT_DATA",
            error="EFA needs at least five problems and three numeric features.",
        )
    n_factors = max(1, min(int(max_factors), frame.shape[1] - 1, frame.shape[0] - 1))
    try:
        from sklearn.decomposition import FactorAnalysis
        from sklearn.preprocessing import StandardScaler
    except Exception as exc:  # pragma: no cover
        return EFAResult(status="LIBRARY_UNAVAILABLE", error=str(exc))

    try:
        scaled = StandardScaler().fit_transform(frame.to_numpy(dtype=float))
        model = FactorAnalysis(n_components=n_factors, random_state=random_state, max_iter=1000)
        model.fit(scaled)
    except Exception as exc:
        return EFAResult(status="FIT_ERROR", error=f"EFA fit failed: {exc}")

    loadings = np.asarray(model.components_, dtype=float)
    factors: list[dict[str, Any]] = []
    for factor_index in range(loadings.shape[0]):
        entries = [
            {
                "variable_name": numeric[feature_index],
                "loading": float(loadings[factor_index, feature_index]),
            }
            for feature_index in range(len(numeric))
        ]
        entries.sort(key=lambda item: abs(item["loading"]), reverse=True)
        factors.append({"factor_id": f"F{factor_index + 1}", "loadings": entries})
    uniqueness = {
        name: float(value) for name, value in zip(numeric, np.asarray(model.noise_variance_, dtype=float), strict=False)
    }
    return EFAResult(
        status="OK",
        n_factors=n_factors,
        features=numeric,
        factors=factors,
        uniqueness=uniqueness,
    )
