"""
engine/normalization.py
Low-level numeric helpers used by feature functions.

FIXES:
  - threshold_map: original sorted thresholds ascending and returned score
    for the FIRST limit >= val.  This was wrong for sequences like
    [(135,75),(145,45),(160,15)] where the intent is "the higher the value,
    the lower the score".  Now uses linear interpolation between breakpoints
    so the mapping is smooth and direction-agnostic.
  - rolling_zscore: guard against single-element history (std=0).
  - vol_adjusted_score: clamp output to [0, 100].
"""

import numpy as np
from typing import List


def rolling_zscore(current: float, history: List[float], window: int = 30) -> float:
    """Z-score of *current* relative to the trailing *window* values in history."""
    arr = np.array((history[-window:] if len(history) >= window else history) + [current],
                   dtype=float)
    std = float(np.std(arr, ddof=0))
    return 0.0 if std == 0 else float((current - np.mean(arr)) / std)


def sigmoid_scale(
    val: float,
    center: float = 0.0,
    width: float = 1.0,
    out_min: float = 0.0,
    out_max: float = 100.0,
) -> float:
    """Map any real value to [out_min, out_max] via sigmoid."""
    return out_min + (out_max - out_min) / (1.0 + np.exp(-width * (val - center)))


def threshold_map(val: float, thresholds: List[tuple]) -> float:
    """
    Piecewise-linear interpolation between (breakpoint, score) pairs.

    Thresholds are sorted by breakpoint automatically — direction of the
    score values does not matter (can go up or down).

    Examples
    --------
    threshold_map(148, [(135, 75), (145, 45), (160, 15)])
      → interpolates between (145,45) and (160,15) → ~41.0

    threshold_map(3.8, [(3, 10), (5, 50), (8, 90)])
      → interpolates between (3,10) and (5,50) → ~26.0
    """
    pts = sorted(thresholds, key=lambda x: x[0])  # sort by breakpoint ascending

    # Below lowest breakpoint → return first score
    if val <= pts[0][0]:
        return float(pts[0][1])

    # Above highest breakpoint → return last score
    if val >= pts[-1][0]:
        return float(pts[-1][1])

    # Linear interpolation between surrounding breakpoints
    for i in range(len(pts) - 1):
        x0, y0 = pts[i]
        x1, y1 = pts[i + 1]
        if x0 <= val <= x1:
            t = (val - x0) / (x1 - x0)
            return float(y0 + t * (y1 - y0))

    return float(pts[-1][1])  # fallback (should not reach)


def vol_adjusted_score(raw_score: float, atr_pct: float) -> float:
    """Multiply raw score by ATR regime factor, clamped to [0, 100]."""
    if atr_pct < 3.0:
        adjusted = raw_score * 1.15
    elif atr_pct > 5.0:
        adjusted = raw_score * 0.80
    else:
        adjusted = raw_score
    return float(np.clip(adjusted, 0.0, 100.0))
