from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.models.emission_source import EmissionSource
from app.models.natural_gas_timeseries import NaturalGasTimeseries
from app.models.project import Project
from app.models.purchased_electricity_timeseries import PurchasedElectricityTimeseries
from app.services.carbon_market_service import calculate_quota_gap
from app.utils.time_series_utils import (
    detect_gaps,
    detect_outliers,
    handle_outliers,
    interpolate_gaps,
    score_data_quality,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Forecast cap: prevent unbounded growth
# ---------------------------------------------------------------------------
MAX_FORECAST_RATIO = 1.20  # forecast values cannot exceed 120% of historical max


@dataclass
class ForecastResult:
    model_used: str
    history: pd.DataFrame
    future: pd.DataFrame
    trend: str
    reduction_warning: str
    compliance_gap_preview: dict[str, Any]
    data_quality: dict[str, Any] = field(default_factory=dict)
    interpolation_count: int = 0
    outlier_count: int = 0
    # Sub-item forecasts (NG / PE)
    ng_future: pd.DataFrame | None = None
    pe_future: pd.DataFrame | None = None
    # Debug & diagnostics
    debug_info: dict[str, Any] = field(default_factory=dict)
    scope_ratio: dict[str, float] = field(default_factory=dict)


# ===================================================================
# Data loading
# ===================================================================

def _load_ng_timeseries(db: Session, project_id: int) -> pd.DataFrame:
    """Load natural gas timeseries aggregated by month (Scope 1)."""
    rows = (
        db.query(NaturalGasTimeseries)
        .filter(NaturalGasTimeseries.project_id == project_id)
        .order_by(NaturalGasTimeseries.period_start.asc())
        .all()
    )
    if not rows:
        return pd.DataFrame(columns=["ds", "y"])
    records: dict[str, float] = {}
    for r in rows:
        dt = r.period_start or r.period_end
        if dt is None:
            continue
        key = dt.strftime("%Y-%m")
        records[key] = records.get(key, 0.0) + float(r.co2e or 0.0)
    data = [{"ds": pd.to_datetime(k), "y": v} for k, v in sorted(records.items())]
    return pd.DataFrame(data)


def _load_pe_timeseries(db: Session, project_id: int) -> pd.DataFrame:
    """Load purchased electricity timeseries aggregated by month (Scope 2)."""
    rows = (
        db.query(PurchasedElectricityTimeseries)
        .filter(PurchasedElectricityTimeseries.project_id == project_id)
        .order_by(PurchasedElectricityTimeseries.period_start.asc())
        .all()
    )
    if not rows:
        return pd.DataFrame(columns=["ds", "y"])
    records: dict[str, float] = {}
    for r in rows:
        dt = r.period_start or r.period_end
        if dt is None:
            continue
        key = dt.strftime("%Y-%m")
        records[key] = records.get(key, 0.0) + float(r.co2e or 0.0)
    data = [{"ds": pd.to_datetime(k), "y": v} for k, v in sorted(records.items())]
    return pd.DataFrame(data)


def _load_emission_source_timeseries(db: Session, project_id: int) -> pd.DataFrame:
    """Load emission_sources data aggregated by month (supplement to NG+PE)."""
    rows = (
        db.query(EmissionSource)
        .filter(EmissionSource.project_id == project_id)
        .order_by(EmissionSource.created_at.asc())
        .all()
    )
    if not rows:
        return pd.DataFrame(columns=["ds", "y"])
    records: dict[str, float] = {}
    for r in rows:
        dt = r.period_end or r.period_start or (r.created_at.date() if r.created_at else None)
        if dt is None:
            continue
        key = dt.strftime("%Y-%m")
        records[key] = records.get(key, 0.0) + float(r.co2e or 0.0)
    data = [{"ds": pd.to_datetime(k), "y": v} for k, v in sorted(records.items())]
    return pd.DataFrame(data)


def _load_total_timeseries(db: Session, project_id: int) -> pd.DataFrame:
    """Load combined total emission from NG + PE + other emission sources."""
    ng = _load_ng_timeseries(db, project_id)
    pe = _load_pe_timeseries(db, project_id)
    es = _load_emission_source_timeseries(db, project_id)

    merged: dict[str, float] = {}
    for df in (ng, pe, es):
        for _, row in df.iterrows():
            key = row["ds"].strftime("%Y-%m")
            merged[key] = merged.get(key, 0.0) + float(row["y"] or 0.0)

    if not merged:
        return pd.DataFrame(columns=["ds", "y"])
    data = [{"ds": pd.to_datetime(k), "y": v} for k, v in sorted(merged.items())]
    return pd.DataFrame(data)


# ===================================================================
# Preprocessing
# ===================================================================

def _resample(df: pd.DataFrame, granularity: str) -> pd.DataFrame:
    if df.empty:
        return df
    freq = "MS" if granularity == "month" else "D"
    res = (
        df.set_index("ds")[["y"]]
        .resample(freq)
        .sum(min_count=1)
        .reset_index()
        .rename(columns={"ds": "ds", "y": "y"})
    )
    return res


def _preprocess(history: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    if history.empty:
        return history, {
            "quality": {"score": 0.0, "flags": ["empty"]},
            "gap_count": 0,
            "outlier_count": 0,
            "interpolation_count": 0,
        }

    gaps_df = detect_gaps(history)
    date_gap_count = len(gaps_df)
    nan_in_y = int(history["y"].isna().sum())
    total_missing = max(date_gap_count, nan_in_y)

    if nan_in_y > 0:
        logger.info("Detected %d NaN value(s) in time series; filling via seasonal interpolation.", nan_in_y)
        history = _fill_nan_values(history)

    if date_gap_count > 0:
        logger.info("Detected %d date gap(s) in time series; filling via seasonal interpolation.", date_gap_count)
        history = interpolate_gaps(history, method="seasonal")

    quality = score_data_quality(history)

    y = history["y"]
    outlier_count = 0
    if y.notna().sum() >= 4:
        outlier_mask = detect_outliers(y, method="mad")
        outlier_count = int(outlier_mask.sum())
        if outlier_count > 0:
            if outlier_count / max(len(y), 1) > 0.3:
                logger.warning("High outlier ratio (%d/%d). Clipping outliers.", outlier_count, len(y))
            history["y"] = handle_outliers(y, outlier_mask, method="clip")
            quality = score_data_quality(history)

    interpolation_count = (
        int(history["_interpolated"].sum()) if "_interpolated" in history.columns else total_missing
    )

    return history, {
        "quality": quality,
        "gap_count": date_gap_count,
        "outlier_count": outlier_count,
        "interpolation_count": interpolation_count,
    }


def _fill_nan_values(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    if "_interpolated" not in result.columns:
        result["_interpolated"] = False
    date_indexed = result.set_index("ds")
    if "y" in date_indexed.columns:
        nan_mask = date_indexed["y"].isna()
        if nan_mask.any():
            result["_interpolated"] = result["_interpolated"] | nan_mask.values
            date_indexed["y"] = _seasonal_fill_series(date_indexed["y"])
            date_indexed["y"] = date_indexed["y"].ffill().bfill()
    result = date_indexed.reset_index()
    return result


def _seasonal_fill_series(series: pd.Series) -> pd.Series:
    s = series.copy()
    if s.notna().sum() < 2:
        return s
    monthly_avg = s.groupby(s.index.month).transform("mean")
    return s.fillna(monthly_avg)


# ===================================================================
# Constraint helpers
# ===================================================================

def _apply_value_cap(pred: np.ndarray, history_y: np.ndarray, max_ratio: float = MAX_FORECAST_RATIO) -> np.ndarray:
    """Cap forecast values at max_ratio * historical_max to prevent unbounded growth."""
    hist_max = float(np.max(history_y)) if len(history_y) > 0 else 0.0
    cap = hist_max * max_ratio
    capped = np.minimum(pred, cap)
    n_capped = int(np.sum(pred > cap))
    if n_capped > 0:
        logger.info("Capped %d forecast value(s) at %.2f (%.0f%% of historical max %.2f).",
                     n_capped, cap, max_ratio * 100, hist_max)
    return capped


def _calc_confidence_intervals(
    residuals: np.ndarray,
    n_history: int,
    horizon: int,
    x_mean: float,
    ssx: float,
) -> dict[str, np.ndarray]:
    """Calculate 80% and 95% confidence intervals that widen with horizon.

    Uses prediction interval formula:
        SE_h = rse * sqrt(1 + 1/n + (x_h - x_mean)^2 / SSX)

    Returns dict with keys: yhat_lower_80, yhat_upper_80, yhat_lower_95, yhat_upper_95
    """
    rse = float(np.sqrt(np.sum(residuals ** 2) / max(n_history - 2, 1)))
    # t-critical values: 80% ≈ 1.282, 95% ≈ 1.96 (large-sample approx)
    t_80 = 1.282
    t_95 = 1.96

    lowers_80 = np.zeros(horizon, dtype=float)
    uppers_80 = np.zeros(horizon, dtype=float)
    lowers_95 = np.zeros(horizon, dtype=float)
    uppers_95 = np.zeros(horizon, dtype=float)

    for h in range(horizon):
        x_h = float(n_history + h)
        if ssx < 1e-9:
            se_h = rse
        else:
            se_h = rse * np.sqrt(1.0 + 1.0 / n_history + (x_h - x_mean) ** 2 / ssx)

        margin_80 = t_80 * se_h
        margin_95 = t_95 * se_h
        lowers_80[h] = margin_80
        uppers_80[h] = margin_80
        lowers_95[h] = margin_95
        uppers_95[h] = margin_95

    return {
        "margin_80": lowers_80,   # same as uppers_80 (symmetric)
        "margin_95": lowers_95,
    }


# ===================================================================
# Forecasting models
# ===================================================================

def _forecast_linear(history: pd.DataFrame, periods: int, freq: str) -> pd.DataFrame:
    y = history["y"].to_numpy(dtype=float)
    x = np.arange(len(y), dtype=float)
    n = len(y)

    if n == 0:
        pred = np.zeros(periods, dtype=float)
        ci80 = np.zeros(periods, dtype=float)
        ci95 = np.zeros(periods, dtype=float)
    elif n == 1:
        val = max(float(y[0]), 0.0)
        pred = np.full(periods, val, dtype=float)
        ci80 = np.full(periods, 0.0, dtype=float)
        ci95 = np.full(periods, 0.0, dtype=float)
    else:
        if n > 10:
            slope, intercept = _theil_sen_slope(x, y)
        else:
            slope, intercept = np.polyfit(x, y, 1)

        fx = np.arange(n, n + periods, dtype=float)
        pred = slope * fx + intercept
        pred = np.maximum(pred, 0.0)

        y_pred_line = slope * x + intercept
        residuals = y - y_pred_line
        x_mean = float(np.mean(x))
        ssx = float(np.sum((x - x_mean) ** 2))

        ci = _calc_confidence_intervals(residuals, n, periods, x_mean, ssx)
        ci80 = ci["margin_95"]  # We'll distinguish 80/95 at the API layer
        ci95 = ci["margin_95"]

    future_ds = pd.date_range(start=history["ds"].iloc[-1], periods=periods + 1, freq=freq)[1:]
    return pd.DataFrame({
        "ds": future_ds,
        "yhat": pred,
        "yhat_lower": np.maximum(pred - ci95, 0.0),
        "yhat_upper": np.maximum(pred + ci95, 0.0),
        "yhat_lower_80": np.maximum(pred - ci80 * 0.654, 0.0),  # 80% / 95% ≈ 1.282/1.96
        "yhat_upper_80": np.maximum(pred + ci80 * 0.654, 0.0),
        "yhat_lower_95": np.maximum(pred - ci95, 0.0),
        "yhat_upper_95": np.maximum(pred + ci95, 0.0),
    })


def _theil_sen_slope(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    n = len(x)
    slopes: list[float] = []
    max_pairs = 2000
    if n * (n - 1) // 2 > max_pairs:
        rng = np.random.default_rng(42)
        idx_pairs = set()
        while len(slopes) < max_pairs:
            i, j = rng.integers(0, n, size=2)
            if i >= j:
                continue
            key = (i, j)
            if key in idx_pairs:
                continue
            idx_pairs.add(key)
            denom = x[j] - x[i]
            if abs(denom) > 1e-9:
                slopes.append((y[j] - y[i]) / denom)
    else:
        for i in range(n):
            for j in range(i + 1, n):
                denom = x[j] - x[i]
                if abs(denom) > 1e-9:
                    slopes.append((y[j] - y[i]) / denom)
    slope = float(np.median(slopes)) if slopes else 0.0
    intercept = float(np.median(y - slope * x))
    return slope, intercept


def _forecast_prophet(history: pd.DataFrame, periods: int, freq: str) -> pd.DataFrame | None:
    try:
        from prophet import Prophet  # type: ignore
    except Exception:
        return None
    model = Prophet(
        yearly_seasonality=True,
        weekly_seasonality=(freq == "D"),
        daily_seasonality=False,
    )
    model.fit(history[["ds", "y"]])
    future = model.make_future_dataframe(periods=periods, freq=freq, include_history=False)
    fcst = model.predict(future)
    result = fcst[["ds", "yhat"]].copy()
    if "yhat_lower" in fcst.columns and "yhat_upper" in fcst.columns:
        result["yhat_lower"] = fcst["yhat_lower"]
        result["yhat_upper"] = fcst["yhat_upper"]
    else:
        result["yhat_lower"] = result["yhat"]
        result["yhat_upper"] = result["yhat"]
    # Prophet doesn't natively provide 80% CI separate from its built-in, use scaling
    result["yhat_lower_80"] = result["yhat"] - (result["yhat"] - result["yhat_lower"]) * 0.654
    result["yhat_upper_80"] = result["yhat"] + (result["yhat_upper"] - result["yhat"]) * 0.654
    result["yhat_lower_95"] = result["yhat_lower"]
    result["yhat_upper_95"] = result["yhat_upper"]
    return result


def _forecast_holt_winters(
    history: pd.DataFrame, periods: int, freq: str, seasonal_periods: int = 12
) -> pd.DataFrame | None:
    y = history["y"].to_numpy(dtype=float)
    n = len(y)
    m = seasonal_periods
    if n < 2 * m:
        return None

    l0 = float(np.mean(y[:m]))
    b0 = float((np.mean(y[m:2 * m]) - np.mean(y[:m])) / m)
    s0 = y[:m] - l0

    best = _hw_grid_search(y, m, l0, b0, s0)
    if best is None:
        return None
    alpha, beta, gamma = best

    level, trend, seasonal = _hw_fit(y, m, alpha, beta, gamma, l0, b0, s0)
    last_level = float(level[-1])
    last_trend = float(trend[-1])

    preds = np.zeros(periods, dtype=float)
    for h in range(periods):
        s_idx = (n + h) % m
        preds[h] = last_level + (h + 1) * last_trend + float(seasonal[s_idx])
    preds = np.maximum(preds, 0.0)

    fitted = np.array([float(level[t] + seasonal[t % m]) for t in range(n)])
    residuals = y - fitted
    residual_std = float(np.std(residuals, ddof=1)) if len(residuals) > 1 else 0.0

    # CI widens with horizon
    margins_95 = np.zeros(periods, dtype=float)
    margins_80 = np.zeros(periods, dtype=float)
    for h in range(periods):
        se_h = residual_std * np.sqrt(1.0 + (h + 1) / n)
        margins_95[h] = 1.96 * se_h
        margins_80[h] = 1.282 * se_h

    future_ds = pd.date_range(start=history["ds"].iloc[-1], periods=periods + 1, freq=freq)[1:]
    return pd.DataFrame({
        "ds": future_ds,
        "yhat": preds,
        "yhat_lower": np.maximum(preds - margins_95, 0.0),
        "yhat_upper": np.maximum(preds + margins_95, 0.0),
        "yhat_lower_80": np.maximum(preds - margins_80, 0.0),
        "yhat_upper_80": np.maximum(preds + margins_80, 0.0),
        "yhat_lower_95": np.maximum(preds - margins_95, 0.0),
        "yhat_upper_95": np.maximum(preds + margins_95, 0.0),
    })


def _hw_fit(
    y: np.ndarray, m: int, alpha: float, beta: float, gamma: float,
    l0: float, b0: float, s0: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    n = len(y)
    level = np.zeros(n, dtype=float)
    trend = np.zeros(n, dtype=float)
    seasonal = np.zeros(m, dtype=float)
    seasonal[:] = s0

    for t in range(n):
        if t == 0:
            level[t] = alpha * (y[t] - seasonal[t % m]) + (1 - alpha) * (l0 + b0)
            trend[t] = beta * (level[t] - l0) + (1 - beta) * b0
        else:
            level[t] = alpha * (y[t] - seasonal[t % m]) + (1 - alpha) * (level[t - 1] + trend[t - 1])
            trend[t] = beta * (level[t] - level[t - 1]) + (1 - beta) * trend[t - 1]
        seasonal[t % m] = gamma * (y[t] - level[t]) + (1 - gamma) * seasonal[t % m]
    return level, trend, seasonal


def _hw_grid_search(
    y: np.ndarray, m: int, l0: float, b0: float, s0: np.ndarray,
) -> tuple[float, float, float] | None:
    alphas = [0.1, 0.2, 0.3, 0.4, 0.5]
    betas = [0.05, 0.1, 0.2]
    gammas = [0.05, 0.1, 0.2]
    best_rmse = float("inf")
    best_params = None
    for alpha in alphas:
        for beta in betas:
            for gamma in gammas:
                level, trend, seasonal = _hw_fit(y, m, alpha, beta, gamma, l0, b0, s0)
                fitted = np.array([float(level[t] + seasonal[t % m]) for t in range(len(y))])
                rmse = float(np.sqrt(np.mean((y - fitted) ** 2)))
                if rmse < best_rmse:
                    best_rmse = rmse
                    best_params = (alpha, beta, gamma)
    return best_params


def _forecast_lstm(history: pd.DataFrame, periods: int, freq: str) -> pd.DataFrame | None:
    try:
        import tensorflow as tf  # type: ignore
        from tensorflow.keras import Sequential  # type: ignore
        from tensorflow.keras.layers import LSTM, Dense  # type: ignore
    except Exception:
        return None

    y = history["y"].to_numpy(dtype=np.float32)
    if len(y) < 18:
        return None
    seq_len = min(12, max(4, len(y) // 3))
    y_min = float(np.min(y))
    y_max = float(np.max(y))
    scale = (y_max - y_min) if (y_max - y_min) > 1e-9 else 1.0
    y_norm = (y - y_min) / scale

    xs = []
    ys = []
    for i in range(seq_len, len(y_norm)):
        xs.append(y_norm[i - seq_len:i])
        ys.append(y_norm[i])
    x_train = np.array(xs, dtype=np.float32).reshape((-1, seq_len, 1))
    y_train = np.array(ys, dtype=np.float32)

    tf.random.set_seed(42)
    model = Sequential([LSTM(32, input_shape=(seq_len, 1)), Dense(1)])
    model.compile(optimizer="adam", loss="mse")
    model.fit(x_train, y_train, epochs=40, batch_size=8, verbose=0)

    window = y_norm[-seq_len:].tolist()
    preds = []
    for _ in range(periods):
        arr = np.array(window[-seq_len:], dtype=np.float32).reshape((1, seq_len, 1))
        nxt = float(model.predict(arr, verbose=0)[0][0])
        nxt = max(0.0, min(1.0, nxt))
        preds.append(nxt * scale + y_min)
        window.append(nxt)

    preds_arr = np.array(preds, dtype=float)
    future_ds = pd.date_range(start=history["ds"].iloc[-1], periods=periods + 1, freq=freq)[1:]

    # LSTM doesn't natively provide CIs; estimate from in-sample residuals
    fitted = np.zeros(len(y), dtype=float)
    for i in range(seq_len, len(y)):
        arr = y_norm[i - seq_len:i].reshape((1, seq_len, 1))
        fitted[i] = float(model.predict(arr, verbose=0)[0][0]) * scale + y_min
    residuals = y[seq_len:] - fitted[seq_len:]
    rse = float(np.std(residuals, ddof=1)) if len(residuals) > 1 else 0.0
    margins_95 = np.array([rse * 1.96 * np.sqrt(1 + (h + 1) / len(y)) for h in range(periods)])
    margins_80 = margins_95 * 0.654

    return pd.DataFrame({
        "ds": future_ds,
        "yhat": preds_arr,
        "yhat_lower": np.maximum(preds_arr - margins_95, 0.0),
        "yhat_upper": np.maximum(preds_arr + margins_95, 0.0),
        "yhat_lower_80": np.maximum(preds_arr - margins_80, 0.0),
        "yhat_upper_80": np.maximum(preds_arr + margins_80, 0.0),
        "yhat_lower_95": np.maximum(preds_arr - margins_95, 0.0),
        "yhat_upper_95": np.maximum(preds_arr + margins_95, 0.0),
    })


def _ensemble_forecast(
    predictions: list[pd.DataFrame], weights: list[float] | None = None
) -> pd.DataFrame:
    if not predictions:
        raise ValueError("至少需要一个预测结果")
    if len(predictions) == 1:
        return predictions[0]

    n = len(predictions)
    if weights is None:
        weights = [1.0 / n] * n
    total_w = sum(weights)
    weights = [w / total_w for w in weights]

    all_ds = predictions[0]["ds"]
    yhat_combined = np.zeros(len(all_ds), dtype=float)
    yhat_lower_combined = np.full(len(all_ds), np.inf, dtype=float)
    yhat_upper_combined = np.full(len(all_ds), -np.inf, dtype=float)
    yhat_lower_80_combined = np.full(len(all_ds), np.inf, dtype=float)
    yhat_upper_80_combined = np.full(len(all_ds), -np.inf, dtype=float)
    yhat_lower_95_combined = np.full(len(all_ds), np.inf, dtype=float)
    yhat_upper_95_combined = np.full(len(all_ds), -np.inf, dtype=float)

    # Column name pairs for lower/upper CI bounds
    _ci_pairs = [
        ("yhat_lower", "yhat_upper", yhat_lower_combined, yhat_upper_combined),
        ("yhat_lower_80", "yhat_upper_80", yhat_lower_80_combined, yhat_upper_80_combined),
        ("yhat_lower_95", "yhat_upper_95", yhat_lower_95_combined, yhat_upper_95_combined),
    ]
    for pred, w in zip(predictions, weights):
        yhat_combined += pred["yhat"].to_numpy(dtype=float) * w

        for lo_col, hi_col, lo_arr, hi_arr in _ci_pairs:
            if lo_col in pred.columns and hi_col in pred.columns:
                lo = pred[lo_col].to_numpy(dtype=float)
                hi = pred[hi_col].to_numpy(dtype=float)
                np.minimum(lo_arr, lo, out=lo_arr)
                np.maximum(hi_arr, hi, out=hi_arr)
            elif lo_col in pred.columns:
                lo = pred[lo_col].to_numpy(dtype=float)
                np.minimum(lo_arr, lo, out=lo_arr)
                np.maximum(hi_arr, lo, out=hi_arr)

    # Fallback for missing columns
    for lo_arr, hi_arr in [
        (yhat_lower_80_combined, yhat_upper_80_combined),
        (yhat_lower_95_combined, yhat_upper_95_combined),
    ]:
        inf_mask_lo = np.isinf(lo_arr)
        inf_mask_hi = np.isinf(hi_arr)
        lo_arr[inf_mask_lo] = yhat_combined[inf_mask_lo]
        hi_arr[inf_mask_hi] = yhat_combined[inf_mask_hi]

    return pd.DataFrame({
        "ds": all_ds,
        "yhat": yhat_combined,
        "yhat_lower": yhat_lower_95_combined,
        "yhat_upper": yhat_upper_95_combined,
        "yhat_lower_80": yhat_lower_80_combined,
        "yhat_upper_80": yhat_upper_80_combined,
        "yhat_lower_95": yhat_lower_95_combined,
        "yhat_upper_95": yhat_upper_95_combined,
    })


# ===================================================================
# Main prediction entry point
# ===================================================================

def _run_model_cascade(
    history: pd.DataFrame, model: str, periods: int, freq: str
) -> tuple[pd.DataFrame, str]:
    """Run the forecasting model cascade. Returns (future_df, model_used_label)."""
    future: pd.DataFrame | None = None

    if model == "prophet":
        future = _forecast_prophet(history, periods=periods, freq=freq)
        if future is None:
            raise ValueError("Prophet 模型不可用：请安装 prophet 库（pip install prophet）")
        model_used = "prophet"

    elif model == "lstm":
        future = _forecast_lstm(history, periods=periods, freq=freq)
        if future is None:
            raise ValueError("LSTM 模型不可用：请安装 tensorflow 库")
        model_used = "lstm"

    elif model in {"hw", "holt_winters"}:
        future = _forecast_holt_winters(history, periods=periods, freq=freq)
        if future is None:
            raise ValueError(f"Holt-Winters 需要至少 24 个数据点，当前仅 {len(history)} 个")
        model_used = "holt_winters"

    elif model == "linear":
        future = _forecast_linear(history, periods=periods, freq=freq)
        model_used = "linear"

    else:  # auto — ensemble of all available models
        predictions: list[pd.DataFrame] = []
        model_parts: list[str] = []

        linear_future = _forecast_linear(history, periods=periods, freq=freq)
        predictions.append(linear_future)
        model_parts.append("linear")

        hw_future = _forecast_holt_winters(history, periods=periods, freq=freq)
        if hw_future is not None:
            predictions.append(hw_future)
            model_parts.append("hw")

        prophet_future = _forecast_prophet(history, periods=periods, freq=freq)
        if prophet_future is not None:
            predictions.append(prophet_future)
            model_parts.append("prophet")

        future = _ensemble_forecast(predictions)
        model_used = f"ensemble({','.join(model_parts)})"

    # Ensure all CI columns exist
    for col in ("yhat_lower", "yhat_upper", "yhat_lower_80", "yhat_upper_80", "yhat_lower_95", "yhat_upper_95"):
        if col not in future.columns:
            if "80" in col:
                future[col] = future["yhat"]
            elif "95" in col:
                future[col] = future.get("yhat_lower" if "lower" in col else "yhat_upper", future["yhat"])
            else:
                future[col] = future["yhat"]

    return future, model_used


def predict_emission_timeseries(
    db: Session,
    project_id: int,
    *,
    granularity: str = "month",
    model: str = "auto",
    horizon_months: int = 6,
    allocation_method: str = "benchmark",
    warning_threshold_pct: float = 30.0,
    reference_year: int | None = None,
) -> ForecastResult:
    project = db.query(Project).filter(Project.id == project_id, Project.is_deleted == False).first()
    if not project:
        raise ValueError(f"项目 {project_id} 不存在")

    trace_log: list[str] = []
    warnings_triggered: list[str] = []

    # ---- 1. Load data ----
    trace_log.append("Loading total, NG, PE timeseries data...")
    raw_total = _load_total_timeseries(db, project_id)
    raw_ng = _load_ng_timeseries(db, project_id)
    raw_pe = _load_pe_timeseries(db, project_id)

    logger.info("Forecast input: project=%d, model=%s, horizon=%d months, allocation=%s",
                project_id, model, horizon_months, allocation_method)
    logger.info("Loaded: total=%d rows, NG=%d rows, PE=%d rows",
                len(raw_total), len(raw_ng), len(raw_pe))

    history_total = _resample(raw_total, granularity=granularity)
    history_ng = _resample(raw_ng, granularity=granularity)
    history_pe = _resample(raw_pe, granularity=granularity)

    if reference_year is not None:
        history_total = history_total[history_total["ds"].dt.year <= reference_year].copy()
        history_ng = history_ng[history_ng["ds"].dt.year <= reference_year].copy()
        history_pe = history_pe[history_pe["ds"].dt.year <= reference_year].copy()

    if history_total.empty or history_total["y"].notna().sum() < 2:
        raise ValueError("历史数据不足，至少需要2个有效数据点")

    # ---- 2. Preprocess ----
    trace_log.append("Running preprocessing (gap detection, outlier handling)...")
    history_total, prep_report = _preprocess(history_total)
    quality = prep_report.get("quality", {})
    interpolation_count = prep_report.get("interpolation_count", 0)
    outlier_count = prep_report.get("outlier_count", 0)
    trace_log.append(f"Preprocess done: gaps={prep_report.get('gap_count',0)}, outliers={outlier_count}, interpolations={interpolation_count}, quality_score={quality.get('score',0)}")

    # Preprocess NG and PE
    if not history_ng.empty:
        history_ng, _ = _preprocess(history_ng)
    if not history_pe.empty:
        history_pe, _ = _preprocess(history_pe)

    freq = "MS" if granularity == "month" else "D"
    periods = int(horizon_months) if granularity == "month" else int(horizon_months * 30)

    # ---- 3. Calculate historical statistics for constraints ----
    hist_y = history_total["y"].dropna().to_numpy(dtype=float)
    hist_max = float(np.max(hist_y)) if len(hist_y) > 0 else 0.0
    hist_avg = float(np.mean(hist_y)) if len(hist_y) > 0 else 0.0
    hist_std = float(np.std(hist_y, ddof=1)) if len(hist_y) > 1 else 0.0
    cap_value = hist_max * MAX_FORECAST_RATIO

    logger.info("Historical stats: max=%.2f, avg=%.2f, std=%.2f, cap=%.2f",
                hist_max, hist_avg, hist_std, cap_value)
    trace_log.append(f"Historical stats: max={hist_max:.2f}, avg={hist_avg:.2f}, cap={cap_value:.2f}")

    # Scope ratio calculation
    scope_ratio = {}
    if not history_ng.empty and not history_pe.empty:
        # Align NG and PE with total dates
        ng_y = history_ng["y"].dropna().to_numpy(dtype=float)
        pe_y = history_pe["y"].dropna().to_numpy(dtype=float)
        ng_avg = float(np.mean(ng_y)) if len(ng_y) > 0 else 0.0
        pe_avg = float(np.mean(pe_y)) if len(pe_y) > 0 else 0.0
        total_avg = ng_avg + pe_avg
        if total_avg > 1e-9:
            scope_ratio = {
                "scope1_pct": round(ng_avg / total_avg, 4),
                "scope2_pct": round(pe_avg / total_avg, 4),
            }
            logger.info("Scope ratio: Scope1=%.1f%%, Scope2=%.1f%%",
                        scope_ratio["scope1_pct"] * 100, scope_ratio["scope2_pct"] * 100)
            trace_log.append(f"Scope ratio: Scope1={scope_ratio['scope1_pct']*100:.1f}%, Scope2={scope_ratio['scope2_pct']*100:.1f}%")
    else:
        scope_ratio = {"scope1_pct": 0.0, "scope2_pct": 0.0}
        trace_log.append("Scope ratio: insufficient NG/PE data, skipping ratio constraint")

    # ---- 4. Run model cascade for total emission ----
    trace_log.append(f"Running model cascade: model={model}, periods={periods}")
    future, model_used = _run_model_cascade(history_total, model, periods, freq)
    logger.info("Model used: %s", model_used)
    trace_log.append(f"Model: {model_used}")

    # ---- 5. Apply value cap ----
    raw_yhat = future["yhat"].to_numpy(dtype=float).copy()
    capped_yhat = _apply_value_cap(raw_yhat, hist_y)
    n_capped = int(np.sum(raw_yhat != capped_yhat))
    if n_capped > 0:
        trace_log.append(f"Applied value cap: {n_capped} forecast points capped at {cap_value:.2f} (120% of max={hist_max:.2f})")
        future["yhat"] = capped_yhat
        # Also cap CI bounds to stay consistent
        for col in ("yhat_lower", "yhat_upper", "yhat_lower_80", "yhat_upper_80", "yhat_lower_95", "yhat_upper_95"):
            if col in future.columns:
                future[col] = future[col].clip(upper=cap_value * 1.05)  # Allow CI slightly above cap

    # ---- 6. Forecast NG and PE separately (sub-item forecasts) ----
    ng_future: pd.DataFrame | None = None
    pe_future: pd.DataFrame | None = None

    if not history_ng.empty and len(history_ng) >= 2:
        try:
            ng_future, _ = _run_model_cascade(history_ng, model, periods, freq)
            ng_y_hist = history_ng["y"].dropna().to_numpy(dtype=float)
            ng_capped = _apply_value_cap(ng_future["yhat"].to_numpy(dtype=float), ng_y_hist)
            ng_future["yhat"] = ng_capped
            trace_log.append(f"NG sub-forecast: {len(ng_future)} periods")
        except Exception as e:
            logger.warning("NG sub-forecast failed: %s", e)
            trace_log.append(f"NG sub-forecast failed: {e}")

    if not history_pe.empty and len(history_pe) >= 2:
        try:
            pe_future, _ = _run_model_cascade(history_pe, model, periods, freq)
            pe_y_hist = history_pe["y"].dropna().to_numpy(dtype=float)
            pe_capped = _apply_value_cap(pe_future["yhat"].to_numpy(dtype=float), pe_y_hist)
            pe_future["yhat"] = pe_capped
            trace_log.append(f"PE sub-forecast: {len(pe_future)} periods")
        except Exception as e:
            logger.warning("PE sub-forecast failed: %s", e)
            trace_log.append(f"PE sub-forecast failed: {e}")

    # ---- 7. Apply scope ratio constraint to sub-item forecasts ----
    if ng_future is not None and pe_future is not None and scope_ratio.get("scope1_pct", 0) > 0:
        sp1 = scope_ratio["scope1_pct"]
        sp2 = scope_ratio["scope2_pct"]
        for i in range(min(len(ng_future), len(pe_future))):
            total_i = float(future["yhat"].iloc[i]) if i < len(future) else 0.0
            ng_val = float(ng_future["yhat"].iloc[i])
            pe_val = float(pe_future["yhat"].iloc[i])
            sub_total = ng_val + pe_val
            if sub_total > 1e-9 and total_i > 1e-9:
                # Adjust NG and PE to maintain historical ratio while keeping total consistent
                target_ng = total_i * sp1 / (sp1 + sp2) if (sp1 + sp2) > 0 else ng_val
                target_pe = total_i * sp2 / (sp1 + sp2) if (sp1 + sp2) > 0 else pe_val
                # Blend: 70% model output, 30% historical ratio constraint
                alpha_blend = 0.3
                ng_future["yhat"].iloc[i] = ng_val * (1 - alpha_blend) + target_ng * alpha_blend
                pe_future["yhat"].iloc[i] = pe_val * (1 - alpha_blend) + target_pe * alpha_blend
        trace_log.append(f"Applied scope ratio constraint (blend=0.3): Scope1={sp1*100:.1f}%, Scope2={sp2*100:.1f}%")

    # ---- 8. Trend & warning ----
    base = float(history_total["y"].dropna().iloc[-1]) if history_total["y"].notna().any() else 0.0
    tail = float(future["yhat"].iloc[-1]) if not pd.isna(future["yhat"].iloc[-1]) else 0.0

    # YoY comparison: compare last forecast month vs same month in history (if available)
    # or fall back to simple end-to-end comparison
    delta_pct = ((tail - base) / base * 100.0) if base > 0 else 0.0

    # Trend classification
    if delta_pct > 10:
        trend = "快速上升"
    elif delta_pct > 2:
        trend = "缓慢上升"
    elif delta_pct < -10:
        trend = "快速下降"
    elif delta_pct < -2:
        trend = "缓慢下降"
    else:
        trend = "基本持平"

    # Warning: based on quota gap + significant YoY increase (>30%)
    quota_rows = []
    for _, row_f in future.iterrows():
        total_val = float(row_f["yhat"]) if not pd.isna(row_f["yhat"]) else 0.0
        free_quota, gap = calculate_quota_gap(total_val, allocation_method)
        quota_rows.append({
            "date": str(pd.to_datetime(row_f["ds"]).date()),
            "predicted_total_emission": round(total_val, 4),
            "free_quota": round(float(free_quota), 4),
            "quota_gap": round(float(gap), 4),
        })

    max_gap = max((x["quota_gap"] for x in quota_rows), default=0.0)
    has_quota_risk = max_gap > 0
    significant_yoy = abs(delta_pct) > warning_threshold_pct

    if has_quota_risk and significant_yoy:
        reduction_warning = (
            f"趋势：{trend}；预警：预测期排放同比增长{delta_pct:+.1f}%，"
            f"超出免费配额{max_gap:.2f} tCO₂e，需关注配额缺口风险"
        )
        warnings_triggered.append(f"quota_gap_risk: max_gap={max_gap:.2f}")
        warnings_triggered.append(f"yoy_change: {delta_pct:+.1f}% > threshold {warning_threshold_pct}%")
    elif has_quota_risk:
        reduction_warning = (
            f"趋势：{trend}；提示：预测期存在配额缺口（最大{max_gap:.2f} tCO₂e），"
            f"但同比变化{delta_pct:+.1f}%，未触发预警阈值"
        )
        warnings_triggered.append(f"quota_gap_only: max_gap={max_gap:.2f}")
    elif significant_yoy:
        reduction_warning = (
            f"趋势：{trend}；预警：预测期排放同比增长{delta_pct:+.1f}%，"
            f"超过{ warning_threshold_pct}%预警阈值，建议关注排放趋势"
        )
        warnings_triggered.append(f"yoy_only: {delta_pct:+.1f}% > threshold {warning_threshold_pct}%")
    else:
        reduction_warning = f"趋势：{trend}；排放量在配额范围内，暂无履约风险"
        warnings_triggered.append("no_risk")

    logger.info("Trend: %s, Delta: %.1f%%, Warning: %s", trend, delta_pct, reduction_warning)
    trace_log.append(f"Trend: {trend}, Delta: {delta_pct:+.1f}%")
    trace_log.append(f"Warning: {reduction_warning}")

    # ---- 9. Build debug info ----
    debug_info = {
        "model_input": {
            "n_history_points": int(len(history_total)),
            "historical_max": round(hist_max, 4),
            "historical_avg": round(hist_avg, 4),
            "historical_std": round(hist_std, 4),
            "data_quality": quality,
            "reference_year": reference_year,
        },
        "model_output": {
            "model_used": model_used,
            "raw_yhat_sample": [round(float(x), 4) for x in raw_yhat[:5].tolist()],
            "capped_yhat_sample": [round(float(x), 4) for x in capped_yhat[:5].tolist()],
            "n_capped": n_capped,
            "cap_value": round(cap_value, 4),
        },
        "confidence_intervals": {
            "steps": [
                {
                    "horizon": h + 1,
                    "yhat": round(float(future["yhat"].iloc[h]), 4) if h < len(future) else None,
                    "lower_80": round(float(future["yhat_lower_80"].iloc[h]), 4) if h < len(future) and "yhat_lower_80" in future.columns else None,
                    "upper_80": round(float(future["yhat_upper_80"].iloc[h]), 4) if h < len(future) and "yhat_upper_80" in future.columns else None,
                    "lower_95": round(float(future["yhat_lower_95"].iloc[h]), 4) if h < len(future) and "yhat_lower_95" in future.columns else None,
                    "upper_95": round(float(future["yhat_upper_95"].iloc[h]), 4) if h < len(future) and "yhat_upper_95" in future.columns else None,
                }
                for h in range(min(len(future), horizon_months))
            ]
        },
        "constraints": {
            "cap_applied": n_capped > 0,
            "cap_ratio": MAX_FORECAST_RATIO,
            "cap_value": round(cap_value, 4),
            "scope_ratio_enforced": scope_ratio.get("scope1_pct", 0) > 0,
            "scope_ratio": scope_ratio,
        },
        "warnings": warnings_triggered,
        "trace": trace_log,
    }

    compliance_preview = {
        "allocation_method": allocation_method,
        "max_gap": round(max_gap, 4),
        "min_gap": round(min((x["quota_gap"] for x in quota_rows), default=0.0), 4),
        "periods": quota_rows,
    }

    logger.info("Forecast complete: model=%s, trend=%s, max_gap=%.2f", model_used, trend, max_gap)

    return ForecastResult(
        model_used=model_used,
        history=history_total,
        future=future,
        trend=trend,
        reduction_warning=reduction_warning,
        compliance_gap_preview=compliance_preview,
        data_quality=quality,
        interpolation_count=interpolation_count,
        outlier_count=outlier_count,
        ng_future=ng_future,
        pe_future=pe_future,
        debug_info=debug_info,
        scope_ratio=scope_ratio,
    )
