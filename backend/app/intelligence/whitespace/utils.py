from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime

import numpy as np
from scipy.ndimage import gaussian_filter

_EFFORT_SCORES = {
    "low": 2.0,
    "medium": 3.5,
    "medium-high": 4.0,
    "high": 5.0,
    "unknown": 2.0,
    "": 2.0,
}


def normalize_label(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text or text in {"unknown", "none", "null", "n/a", "na", "other"}:
        return None
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = text.strip("_")
    return text or None


def parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def effort_score(value: object) -> float:
    label = normalize_label(value)
    if label is None:
        return _EFFORT_SCORES["unknown"]
    return _EFFORT_SCORES.get(label, 2.0)


def mean(values: Sequence[float]) -> float:
    finite = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    return sum(finite) / len(finite) if finite else 0.0


def top_values(values: Iterable[object | None], limit: int = 3) -> tuple[str, ...]:
    counts: Counter[str] = Counter()
    for value in values:
        label = normalize_label(value)
        if label:
            counts[label] += 1
    if not counts:
        return ()
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return tuple(label for label, _ in ordered[:limit])


def jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    a, b = set(left), set(right)
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def minmax_scores(raw_scores: Sequence[float]) -> list[float]:
    if not raw_scores:
        return []
    finite = [float(value) if math.isfinite(float(value)) else 0.0 for value in raw_scores]
    low, high = min(finite), max(finite)
    if len(finite) == 1:
        return [min(1.0, max(0.0, finite[0] / 2.0))]
    if math.isclose(high, low):
        return [1.0 if high > 0 else 0.0 for _ in finite]
    return [(value - low) / (high - low) for value in finite]


def deterministic_id(prefix: str, parts: Sequence[object]) -> str:
    payload = "|".join(str(part) for part in parts)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def percentile(values: Sequence[float], percentile_value: float) -> float:
    if not values:
        return 0.0
    return float(np.percentile(np.asarray(values, dtype=float), percentile_value))


def gower_distance(left: Mapping[str, object], right: Mapping[str, object], fields: Sequence[str]) -> float:
    compared = 0
    total = 0.0
    for name in fields:
        a = normalize_label(left.get(name))
        b = normalize_label(right.get(name))
        if a is None or b is None:
            continue
        compared += 1
        total += 0.0 if a == b else 1.0
    return total / compared if compared else 0.0


def kde_2d(
    xs: Sequence[float],
    ys: Sequence[float],
    weights: Sequence[float],
    grid_shape: tuple[int, int],
    bounds: tuple[float, float, float, float],
) -> np.ndarray:
    histogram = np.zeros(grid_shape, dtype=float)
    x_array = np.asarray(xs, dtype=float)
    y_array = np.asarray(ys, dtype=float)
    if x_array.size == 0 or y_array.size == 0:
        return histogram
    x0, x1, y0, y1 = bounds
    if math.isclose(x0, x1) or math.isclose(y0, y1):
        return histogram
    x_bins = np.linspace(x0, x1, grid_shape[1] + 1)
    y_bins = np.linspace(y0, y1, grid_shape[0] + 1)
    for x, y, weight in zip(x_array, y_array, weights, strict=True):
        if not all(math.isfinite(float(value)) for value in (x, y, weight)):
            continue
        x_index = int(np.clip(np.searchsorted(x_bins, x, side="right") - 1, 0, grid_shape[1] - 1))
        y_index = int(np.clip(np.searchsorted(y_bins, y, side="right") - 1, 0, grid_shape[0] - 1))
        histogram[y_index, x_index] += max(0.0, float(weight))
    x_values = x_array
    y_values = y_array
    x_span = max(float(np.std(x_values)), (x1 - x0) / grid_shape[1], 1e-9)
    y_span = max(float(np.std(y_values)), (y1 - y0) / grid_shape[0], 1e-9)
    sigma = (
        max(1.0, y_span / ((y1 - y0) / grid_shape[0])),
        max(1.0, x_span / ((x1 - x0) / grid_shape[1])),
    )
    smoothed = gaussian_filter(histogram, sigma=sigma, mode="constant", truncate=4.0)
    peak = float(smoothed.max()) if smoothed.size else 0.0
    return smoothed / peak if peak > 0 else smoothed
