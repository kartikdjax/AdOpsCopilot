"""
Anomaly detection: flags days where a metric deviates significantly from
its recent trailing baseline.

IMPORTANT design detail: the baseline for day N is computed from days
BEFORE N only (a trailing window, shifted by 1), never including day N
itself. If you included the anomaly day in its own baseline window, a
sudden crash would drag its own rolling average down too, understating
the z-score and potentially hiding the anomaly - especially with small
windows. This is a real, easy-to-miss bug in naive anomaly detection.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True, slots=True)
class Anomaly:
    date: pd.Timestamp
    metric: str
    actual_value: float
    expected_value: float
    z_score: float
    severity: str  # "moderate" | "severe"


def detect_anomalies(daily_df: pd.DataFrame, metric_col: str,
                      window: int = 7, z_threshold: float = 2.0) -> list[Anomaly]:
    """
    Args:
        daily_df: output of events_to_daily_stats(), sorted by event_date.
        metric_col: column to check, e.g. "ctr_pct".
        window: how many PRIOR days form the baseline for each day.
        z_threshold: |z| above this is flagged as anomalous.
    """
    df = daily_df.copy()
    values = df[metric_col]

    # .shift(1) excludes the current row from its own rolling window -
    # the baseline for day N only ever looks at days < N.
    baseline_mean = values.shift(1).rolling(window=window, min_periods=3).mean()
    baseline_std = values.shift(1).rolling(window=window, min_periods=3).std()

    anomalies: list[Anomaly] = []
    for i in range(len(df)):
        mean_i, std_i = baseline_mean.iloc[i], baseline_std.iloc[i]
        if pd.isna(mean_i) or pd.isna(std_i) or std_i == 0:
            continue  # not enough history yet, or a perfectly flat baseline

        z = (values.iloc[i] - mean_i) / std_i
        if abs(z) >= z_threshold:
            anomalies.append(Anomaly(
                date=df["event_date"].iloc[i], metric=metric_col,
                actual_value=round(float(values.iloc[i]), 4),
                expected_value=round(float(mean_i), 4),
                z_score=round(float(z), 2),
                severity="severe" if abs(z) >= z_threshold * 1.5 else "moderate",
            ))
    return anomalies
