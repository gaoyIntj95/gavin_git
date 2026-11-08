from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Gap detection & interpolation
# ---------------------------------------------------------------------------

def detect_gaps(df: pd.DataFrame, freq: str = "MS") -> pd.DataFrame:
    """Return rows for each contiguous gap in *df*.

    Parameters
    ----------
    df : DataFrame
        Must contain a ``ds`` datetime column and a ``y`` numeric column.
    freq : str
        Pandas frequency string (``"MS"`` for month-start, ``"D"`` for daily).

    Returns
    -------
    pd.DataFrame
        Columns: *gap_start*, *gap_end*, *gap_size*, *position*.
        Empty DataFrame when no gaps are found.
    """
    if df.empty:
        return pd.DataFrame(columns=["gap_start", "gap_end", "gap_size", "position"])

    full_range = pd.date_range(start=df["ds"].min(), end=df["ds"].max(), freq=freq)
    existing = set(pd.to_datetime(df["ds"]))
    missing = [d for d in full_range if d not in existing]
    if not missing:
        return pd.DataFrame(columns=["gap_start", "gap_end", "gap_size", "position"])

    expected_step = _freq_timedelta(freq)

    # Group consecutive missing dates into gap segments
    gaps: list[dict[str, Any]] = []
    seg_start = missing[0]
    prev = missing[0]
    for d in missing[1:]:
        if (d - prev) > expected_step:
            gaps.append(_make_gap_record(seg_start, prev, full_range, freq))
            seg_start = d
        prev = d
    gaps.append(_make_gap_record(seg_start, prev, full_range, freq))
    return pd.DataFrame(gaps)


def _freq_timedelta(freq: str) -> pd.Timedelta:
    """Approximate a timedelta step for a pandas offset alias."""
    if freq in ("MS", "M", "ME"):
        return pd.Timedelta(days=31)
    if freq in ("D",):
        return pd.Timedelta(days=1)
    if freq in ("W",):
        return pd.Timedelta(days=7)
    if freq in ("QS", "QE"):
        return pd.Timedelta(days=92)
    if freq in ("YS", "YE", "Y"):
        return pd.Timedelta(days=366)
    # Fallback: parse generic timedelta-like strings
    return pd.Timedelta(freq)


def _make_gap_record(
    start: pd.Timestamp, end: pd.Timestamp, full_range: pd.DatetimeIndex, freq: str
) -> dict[str, Any]:
    size = len(pd.date_range(start=start, end=end, freq=freq))
    if start == full_range[0]:
        pos = "front"
    elif end == full_range[-1]:
        pos = "end"
    else:
        pos = "middle"
    return {"gap_start": start, "gap_end": end, "gap_size": size, "position": pos}


def interpolate_gaps(
    df: pd.DataFrame, method: str = "linear", freq: str = "MS"
) -> pd.DataFrame:
    """Fill NaN values in *df.y* (and *df.energy*) by *method*.

    Parameters
    ----------
    df : DataFrame
        Must include ``ds``, ``y``, ``energy`` columns.
    method : str
        One of ``"linear"``, ``"ffill"``, ``"seasonal"``, ``"zero"``.
    freq : str
        Frequency string used to align the date range.

    Returns
    -------
    pd.DataFrame
        A copy of *df* with gaps filled.  A boolean column ``_interpolated``
        marks rows whose ``y`` value was imputed.
    """
    result = df.copy()
    if "ds" not in result.columns or "y" not in result.columns:
        return result

    result["ds"] = pd.to_datetime(result["ds"])
    result = result.set_index("ds")
    full_idx = pd.date_range(start=result.index.min(), end=result.index.max(), freq=freq)
    result = result.reindex(full_idx)

    # Record which rows are missing before filling
    was_missing = result["y"].isna()
    result["_interpolated"] = was_missing

    if method == "zero":
        result["y"] = result["y"].fillna(0.0)
        result["energy"] = result["energy"].fillna(0.0)
    elif method == "ffill":
        result["y"] = result["y"].ffill().bfill()
        result["energy"] = result["energy"].ffill().bfill()
    elif method == "seasonal":
        result["y"] = _seasonal_fill(result["y"])
        result["energy"] = _seasonal_fill(result["energy"])
        # Any remaining NaN (e.g. first-year months with no seasonal anchor)
        result["y"] = result["y"].ffill().bfill()
        result["energy"] = result["energy"].ffill().bfill()
    else:  # linear
        result["y"] = result["y"].interpolate(method="linear").ffill().bfill()
        result["energy"] = result["energy"].interpolate(method="linear").ffill().bfill()

    result = result.reset_index().rename(columns={"index": "ds"})
    # Ensure _interpolated is bool type
    result["_interpolated"] = result["_interpolated"].fillna(False).astype(bool)
    return result


def _seasonal_fill(series: pd.Series) -> pd.Series:
    """Fill each NaN with the average of the same calendar month across all years."""
    s = series.copy()
    if s.notna().sum() < 2:
        return s
    monthly_avg = s.groupby(s.index.month).transform("mean")
    return s.fillna(monthly_avg)


# ---------------------------------------------------------------------------
# Outlier detection & handling
# ---------------------------------------------------------------------------

def detect_outliers(
    series: pd.Series, method: str = "mad", threshold: float = 3.0
) -> pd.Series:
    """Return a boolean mask (same index) where ``True`` = outlier.

    Parameters
    ----------
    series : pd.Series
        Numeric values (may contain NaN).
    method : str
        ``"iqr"``, ``"zscore"``, or ``"mad"`` (default).
    threshold : float
        For *zscore*: z-score threshold.  For *iqr*: multiplier on IQR.
        For *mad*: modified z-score threshold.
    """
    clean = series.dropna()
    if len(clean) < 4:
        return pd.Series(False, index=series.index)

    if method == "iqr":
        q1 = np.percentile(clean, 25)
        q3 = np.percentile(clean, 75)
        iqr_val = q3 - q1
        if iqr_val < 1e-9:
            return pd.Series(False, index=series.index)
        lower = q1 - threshold * iqr_val
        upper = q3 + threshold * iqr_val
        return (series < lower) | (series > upper)

    if method == "zscore":
        mean = np.mean(clean)
        std = np.std(clean, ddof=1)
        if std < 1e-9:
            return pd.Series(False, index=series.index)
        z = (series - mean).abs() / std
        return z > threshold

    # MAD (Median Absolute Deviation) — default
    median = np.median(clean)
    mad = np.median(np.abs(clean - median))
    if mad < 1e-9:
        return pd.Series(False, index=series.index)
    modified_z = 0.6745 * (series - median).abs() / mad
    return modified_z > threshold


def handle_outliers(
    series: pd.Series, mask: pd.Series, method: str = "clip"
) -> pd.Series:
    """Replace values where *mask* is True.

    Parameters
    ----------
    series : pd.Series
    mask : pd.Series
        Boolean mask (True = outlier).
    method : str
        ``"clip"`` — clamp to bounds derived from non-outlier values.
        ``"nan"`` — replace with NaN (caller can interpolate later).
        ``"median"`` — replace with the global median of non-outlier values.
    """
    if not mask.any():
        return series

    clean = series[~mask]
    if len(clean) == 0:
        logger.warning("All values flagged as outliers; returning original series.")
        return series

    if method == "nan":
        return series.where(~mask, other=np.nan)

    if method == "median":
        med = np.median(clean)
        return series.where(~mask, other=med)

    # clip
    lower = clean.min()
    upper = clean.max()
    return series.clip(lower=lower, upper=upper)


# ---------------------------------------------------------------------------
# Data quality scoring
# ---------------------------------------------------------------------------

def score_data_quality(df: pd.DataFrame) -> dict[str, Any]:
    """Score the quality of a time-series DataFrame (0-100).

    Dimensions (each 0-25): completeness, continuity, outlier_ratio, span.
    """
    if df.empty or "y" not in df.columns:
        return {
            "score": 0.0,
            "completeness": 0,
            "continuity": 0,
            "outlier_ratio": 0,
            "span": 0,
            "flags": ["empty"],
        }

    y = df["y"]
    n = len(y)
    flags: list[str] = []

    # Completeness (0-25)
    notna_ratio = y.notna().sum() / n if n else 0
    completeness = round(notna_ratio * 25, 1)
    if notna_ratio < 0.7:
        flags.append("high_gap_ratio")

    # Continuity (0-25) — penalise fragmented data
    if "ds" in df.columns and len(df) > 1:
        gaps_df = detect_gaps(df[["ds", "y"]].copy())
        gap_count = len(gaps_df)
        continuity = round(max(0, 25 - gap_count * 5), 1)
    else:
        continuity = 25

    # Outlier ratio (0-25)
    if len(y.dropna()) >= 4:
        outlier_mask = detect_outliers(y, method="mad")
        outlier_pct = outlier_mask.sum() / n if n else 0
        outlier_ratio = round(max(0, 25 - outlier_pct * 125), 1)
        if outlier_pct > 0.2:
            flags.append("high_outlier_ratio")
    else:
        outlier_ratio = 25

    # Span (0-25) — reward longer history
    span_months = n
    span = round(min(25, span_months / 24 * 25), 1)  # max at 24 months

    score = round(completeness + continuity + outlier_ratio + span, 1)
    return {
        "score": score,
        "completeness": completeness,
        "continuity": continuity,
        "outlier_ratio": outlier_ratio,
        "span": span,
        "flags": flags,
    }


