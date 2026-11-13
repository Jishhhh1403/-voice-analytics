"""Exploratory latent-dimension analysis over canonical customer problems."""

from .coefficients import build_equations, calculate_relative_shares
from .feature_builder import (
    FEATURE_SPECS,
    FeatureBuildResult,
    FeatureRow,
    FeatureSpec,
    build_feature_rows,
    resolve_feature_specs,
)

__all__ = [
    "FEATURE_SPECS",
    "FeatureBuildResult",
    "FeatureRow",
    "FeatureSpec",
    "build_feature_rows",
    "build_equations",
    "calculate_relative_shares",
    "resolve_feature_specs",
]
