from __future__ import annotations

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.natural_gas_timeseries import NaturalGasTimeseries
from app.models.purchased_electricity_timeseries import PurchasedElectricityTimeseries
from app.schemas.forecast import (
    ForecastDebugResponse,
    ForecastPoint,
    ForecastRequest,
    ForecastResponse,
    SubItemForecast,
)
from app.services.forecast_service import predict_emission_timeseries

router = APIRouter(prefix="/forecast", tags=["forecast"])


def _df_to_points(
    df: pd.DataFrame, kind: str, has_ci: bool = True
) -> list[ForecastPoint]:
    """Convert a forecast/history DataFrame to a list of ForecastPoint."""
    points: list[ForecastPoint] = []
    for _, row in df.iterrows():
        y_val = float(row["y"]) if kind == "actual" else float(row["yhat"])
        if pd.isna(y_val):
            y_val = None

        kwargs = {"date": str(row["ds"].date()), "value": round(y_val, 4) if y_val is not None else None, "kind": kind}
        if kind == "actual":
            kwargs["is_interpolated"] = bool(row.get("_interpolated", False))
        if has_ci and kind == "forecast":
            for col, target in [
                ("yhat_lower", "yhat_lower"),
                ("yhat_upper", "yhat_upper"),
                ("yhat_lower_80", "yhat_lower_80"),
                ("yhat_upper_80", "yhat_upper_80"),
            ]:
                val = row.get(col)
                kwargs[target] = round(float(val), 4) if val is not None and not pd.isna(val) else None
            # 95% CI maps to main yhat_lower/upper
            for col95, target95 in [
                ("yhat_lower_95", "yhat_lower"),
                ("yhat_upper_95", "yhat_upper"),
            ]:
                val = row.get(col95)
                if val is not None and not pd.isna(val):
                    kwargs[target95] = round(float(val), 4)
        points.append(ForecastPoint(**kwargs))
    return points


def _build_sub_item_forecast(
    source_type: str,
    scope: int,
    history_df: pd.DataFrame | None,
    future_df: pd.DataFrame | None,
    all_dates: list[str],
) -> SubItemForecast:
    """Build a SubItemForecast with history and forecast aligned to all_dates."""
    hist_list: list[dict] = []
    if history_df is not None and not history_df.empty:
        for _, row in history_df.iterrows():
            d = str(row["ds"].date())
            v = float(row["y"]) if not pd.isna(row["y"]) else None
            hist_list.append({"date": d, "value": round(v, 4) if v is not None else None})

    fcst_list: list[dict] = []
    if future_df is not None and not future_df.empty:
        for _, row in future_df.iterrows():
            d = str(row["ds"].date())
            fcst_list.append({
                "date": d,
                "yhat": round(float(row["yhat"]), 4) if not pd.isna(row["yhat"]) else None,
                "yhat_lower_80": round(float(row.get("yhat_lower_80", row["yhat"])), 4),
                "yhat_upper_80": round(float(row.get("yhat_upper_80", row["yhat"])), 4),
                "yhat_lower_95": round(float(row.get("yhat_lower_95", row.get("yhat_lower", row["yhat"]))), 4),
                "yhat_upper_95": round(float(row.get("yhat_upper_95", row.get("yhat_upper", row["yhat"]))), 4),
            })

    return SubItemForecast(source_type=source_type, scope=scope, history=hist_list, forecast=fcst_list)


def _build_echarts(
    history_points: list[ForecastPoint],
    future_points: list[ForecastPoint],
    x_axis: list[str],
    ng_series: list[float | None],
    pe_series: list[float | None],
) -> dict:
    """Build ECharts option with proper confidence band rendering.

    Uses two series for the confidence band:
    - An invisible upper line with a semi-transparent areaStyle
    - A lower line stacked below to create a proper band
    The band fully wraps the forecast line.
    """
    hist_count = len(history_points)
    fcst_count = len(future_points)
    n_total = hist_count + fcst_count

    # Actual values
    full_actual: list[float | None] = [p.value for p in history_points] + [None] * fcst_count

    # Forecast: bridge from last actual for smooth visual connection
    forecast_vals: list[float | None] = [None] * hist_count
    last_actual = next((p.value for p in reversed(history_points) if p.value is not None), None)
    if last_actual is not None and hist_count > 0:
        forecast_vals[hist_count - 1] = last_actual
    for p in future_points:
        forecast_vals.append(p.value)

    # Confidence band (95%): area between lower and upper
    upper_95: list[float | None] = [None] * hist_count
    lower_95: list[float | None] = [None] * hist_count
    if last_actual is not None and hist_count > 0:
        upper_95[hist_count - 1] = last_actual
        lower_95[hist_count - 1] = last_actual
    for p in future_points:
        upper_95.append(p.yhat_upper)
        lower_95.append(p.yhat_lower)

    return {
        "xAxis": x_axis,
        "legend": ["实际综合排放", "天然气排放", "外购电排放", "预测排放", "95%置信区间"],
        "series": [
            {
                "name": "实际综合排放",
                "type": "line",
                "smooth": False,
                "symbol": "circle",
                "symbolSize": 6,
                "lineStyle": {"color": "#2563eb", "width": 2.5},
                "itemStyle": {"color": "#2563eb"},
                "data": full_actual,
                "z": 4,
            },
            {
                "name": "天然气排放",
                "type": "line",
                "smooth": False,
                "symbol": "none",
                "lineStyle": {"color": "#f97316", "width": 1.5, "type": "dashed"},
                "itemStyle": {"color": "#f97316"},
                "data": ng_series,
                "z": 3,
            },
            {
                "name": "外购电排放",
                "type": "line",
                "smooth": False,
                "symbol": "none",
                "lineStyle": {"color": "#8b5cf6", "width": 1.5, "type": "dashed"},
                "itemStyle": {"color": "#8b5cf6"},
                "data": pe_series,
                "z": 3,
            },
            {
                "name": "预测排放",
                "type": "line",
                "smooth": True,
                "symbol": "none",
                "lineStyle": {"color": "#16a34a", "width": 2.5, "type": "dashed"},
                "itemStyle": {"color": "#16a34a"},
                "data": forecast_vals,
                "z": 5,
            },
            {
                "name": "95%置信区间",
                "type": "line",
                "smooth": True,
                "symbol": "none",
                "lineStyle": {"color": "rgba(22,163,74,0.15)", "width": 0},
                "areaStyle": {"color": "rgba(22,163,74,0.12)"},
                "data": upper_95,
                "stack": "confidence-band",
                "z": 1,
            },
            {
                "name": "95%置信区间下界",
                "type": "line",
                "smooth": True,
                "symbol": "none",
                "lineStyle": {"color": "transparent", "width": 0},
                "areaStyle": {"color": "#ffffff"},
                "data": lower_95,
                "stack": "confidence-band",
                "z": 1,
            },
        ],
    }


@router.post("/emission/{project_id}", response_model=ForecastResponse)
def forecast_emission(
    project_id: int,
    payload: ForecastRequest,
    db: Session = Depends(get_db),
) -> ForecastResponse:
    try:
        result = predict_emission_timeseries(
            db=db,
            project_id=project_id,
            granularity=payload.granularity,
            model=payload.model,
            horizon_months=payload.horizon_months,
            allocation_method=payload.allocation_method,
            warning_threshold_pct=payload.warning_threshold_pct,
            reference_year=payload.reference_year,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"预测失败: {exc}")

    # Build history and forecast points
    history_points = _df_to_points(result.history, kind="actual", has_ci=False)
    future_points = _df_to_points(result.future, kind="forecast", has_ci=True)

    hist_dates = [p.date for p in history_points]
    future_dates = [p.date for p in future_points]
    x_axis = hist_dates + future_dates

    # ---- Query raw NG/PE data for per-item emission display (aligned to xAxis) ----
    ng_rows = (
        db.query(NaturalGasTimeseries)
        .filter(NaturalGasTimeseries.project_id == project_id)
        .order_by(NaturalGasTimeseries.period_start.asc())
        .all()
    )
    pe_rows = (
        db.query(PurchasedElectricityTimeseries)
        .filter(PurchasedElectricityTimeseries.project_id == project_id)
        .order_by(PurchasedElectricityTimeseries.period_start.asc())
        .all()
    )

    # Build per-month NG/PE maps using YYYY-MM keys for consistent alignment
    ng_map: dict[str, float] = {}
    for r in ng_rows:
        dt = r.period_start or r.period_end
        if dt:
            key = dt.strftime("%Y-%m")
            ng_map[key] = ng_map.get(key, 0.0) + float(r.co2e or 0.0)

    pe_map: dict[str, float] = {}
    for r in pe_rows:
        dt = r.period_start or r.period_end
        if dt:
            key = dt.strftime("%Y-%m")
            pe_map[key] = pe_map.get(key, 0.0) + float(r.co2e or 0.0)

    # Align to x_axis using YYYY-MM key matching
    def _parse_ym(date_str: str) -> str:
        """Extract YYYY-MM from a date string."""
        return date_str[:7] if len(date_str) >= 7 else date_str

    ng_series = [round(ng_map.get(_parse_ym(d)), 4) if ng_map.get(_parse_ym(d)) else None for d in x_axis]
    pe_series = [round(pe_map.get(_parse_ym(d)), 4) if pe_map.get(_parse_ym(d)) else None for d in x_axis]

    # ---- Build ECharts ----
    echarts = _build_echarts(history_points, future_points, x_axis, ng_series, pe_series)

    # ---- Build sub-item forecasts ----
    sub_items: list[SubItemForecast] = []
    if result.ng_future is not None:
        # Reconstruct history_ng for the sub-item
        ng_hist_df = _build_ng_history_df(db, project_id, payload.reference_year)
        sub_items.append(_build_sub_item_forecast("natural_gas", 1, ng_hist_df, result.ng_future, x_axis))
    if result.pe_future is not None:
        pe_hist_df = _build_pe_history_df(db, project_id, payload.reference_year)
        sub_items.append(_build_sub_item_forecast("purchased_electricity", 2, pe_hist_df, result.pe_future, x_axis))

    # ---- Data sources ----
    data_sources = [
        "natural_gas_timeseries.co2e",
        "purchased_electricity_timeseries.co2e",
        "emission_sources.co2e",
        f"forecast_model:{result.model_used}",
    ]
    if result.interpolation_count > 0:
        data_sources.append(f"interpolated:{result.interpolation_count}")
    if result.outlier_count > 0:
        data_sources.append(f"outliers_clipped:{result.outlier_count}")

    return ForecastResponse(
        project_id=project_id,
        granularity=payload.granularity,
        model_used=result.model_used,
        horizon_months=payload.horizon_months,
        trend=result.trend,
        reduction_warning=result.reduction_warning,
        compliance_gap_preview=result.compliance_gap_preview,
        points=[*history_points, *future_points],
        echarts=echarts,
        data_sources=data_sources,
        data_quality=result.data_quality,
        interpolation_count=result.interpolation_count,
        outlier_count=result.outlier_count,
        sub_item_forecasts=sub_items,
        debug_info=result.debug_info,
        historical_max=float(np.max(result.history["y"].dropna())) if len(result.history) > 0 and result.history["y"].notna().any() else None,
        historical_avg=float(np.mean(result.history["y"].dropna())) if len(result.history) > 0 and result.history["y"].notna().any() else None,
        scope_ratio=result.scope_ratio,
    )


def _build_ng_history_df(db: Session, project_id: int, reference_year: int | None) -> pd.DataFrame | None:
    """Reconstruct NG history dataframe for sub-item display."""
    from app.services.forecast_service import _load_ng_timeseries, _resample, _preprocess
    df = _load_ng_timeseries(db, project_id)
    if df.empty:
        return None
    df = _resample(df, granularity="month")
    if reference_year is not None:
        df = df[df["ds"].dt.year <= reference_year].copy()
    if len(df) >= 2:
        df, _ = _preprocess(df)
    return df


def _build_pe_history_df(db: Session, project_id: int, reference_year: int | None) -> pd.DataFrame | None:
    """Reconstruct PE history dataframe for sub-item display."""
    from app.services.forecast_service import _load_pe_timeseries, _resample, _preprocess
    df = _load_pe_timeseries(db, project_id)
    if df.empty:
        return None
    df = _resample(df, granularity="month")
    if reference_year is not None:
        df = df[df["ds"].dt.year <= reference_year].copy()
    if len(df) >= 2:
        df, _ = _preprocess(df)
    return df


# ---------------------------------------------------------------------------
# Debug endpoint — full forecast diagnostics
# ---------------------------------------------------------------------------

@router.post("/debug/{project_id}", response_model=ForecastDebugResponse)
def debug_forecast(
    project_id: int,
    payload: ForecastRequest,
    db: Session = Depends(get_db),
) -> ForecastDebugResponse:
    """Return complete debug information for a forecast run.

    Includes model inputs, outputs, confidence intervals, constraints,
    warnings, and a step-by-step trace log.
    """
    try:
        result = predict_emission_timeseries(
            db=db,
            project_id=project_id,
            granularity=payload.granularity,
            model=payload.model,
            horizon_months=payload.horizon_months,
            allocation_method=payload.allocation_method,
            warning_threshold_pct=payload.warning_threshold_pct,
            reference_year=payload.reference_year,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"预测失败: {exc}")

    di = result.debug_info

    return ForecastDebugResponse(
        project_id=project_id,
        model_used=result.model_used,
        horizon_months=payload.horizon_months,
        model_input=di.get("model_input", {}),
        model_output=di.get("model_output", {}),
        confidence_intervals=di.get("confidence_intervals", {}),
        constraints=di.get("constraints", {}),
        warnings=di.get("warnings", []),
        trace=di.get("trace", []),
    )
