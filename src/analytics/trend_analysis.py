"""
Trend analysis: given a daily time series for one metric, determine
whether it's increasing, decreasing, or stable, and by how much.

Two complementary methods, deliberately:
  - split-half comparison: robust to noise, easy to explain in plain
    language ("CTR averaged X in the first half, Y in the second half")
  - linear regression slope: catches gradual trends the split-half
    method might miss if the change happens mid-window rather than
    cleanly at the midpoint
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True, slots=True)
class TrendResult:
    metric: str
    direction: str            # "increasing" | "decreasing" | "stable"
    pct_change: float         # (second_half_avg - first_half_avg) / first_half_avg * 100
    first_half_avg: float
    second_half_avg: float
    slope_per_day: float      # linear regression slope, for magnitude/consistency checks


def analyze_trend(daily_df: pd.DataFrame, metric_col: str, stable_threshold_pct: float = 8.0) -> TrendResult:
    """
    Args:
        daily_df: output of events_to_daily_stats() - must have `event_date`
            and `metric_col` columns, one row per day.
        metric_col: which column to analyze, e.g. "ctr_pct", "spend".
        stable_threshold_pct: changes below this magnitude are called
            "stable" rather than a real trend - avoids over-reporting noise
            as a meaningful business signal.
    """
    if len(daily_df) < 4:
        raise ValueError("Need at least 4 days of data to assess a trend meaningfully")

    values = daily_df[metric_col].to_numpy(dtype=float)
    midpoint = len(values) // 2

    first_half_avg = float(values[:midpoint].mean())
    second_half_avg = float(values[midpoint:].mean())

    pct_change = (
        ((second_half_avg - first_half_avg) / first_half_avg) * 100
        if first_half_avg != 0 else 0.0
    )

    day_indices = np.arange(len(values))
    slope_per_day = float(np.polyfit(day_indices, values, deg=1)[0])

    if abs(pct_change) < stable_threshold_pct:
        direction = "stable"
    elif pct_change > 0:
        direction = "increasing"
    else:
        direction = "decreasing"

    return TrendResult(
        metric=metric_col, direction=direction, pct_change=round(pct_change, 2),
        first_half_avg=round(first_half_avg, 4), second_half_avg=round(second_half_avg, 4),
        slope_per_day=round(slope_per_day, 5),
    )
