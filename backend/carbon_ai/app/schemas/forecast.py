from __future__ import annotations

from pydantic import BaseModel, Field


class ForecastRequest(BaseModel):
    granularity: str = Field(default="month", pattern=r"^(month|day)$")
    model: str = Field(default="auto", pattern=r"^(auto|prophet|lstm|hw|holt_winters|linear|ensemble)$")
    horizon_months: int = Field(default=6, ge=1, le=24)
    allocation_method: str = Field(default="benchmark", pattern=r"^(grandfathering|benchmark|hybrid)$")
    warning_threshold_pct: float = Field(default=30.0, ge=0.0, le=100.0)
    reference_year: int | None = Field(default=None, ge=2000, le=2100)


class SubItemForecast(BaseModel):
    """Per-source forecast (natural gas / purchased electricity)."""
    source_type: str  # "natural_gas" | "purchased_electricity"
    scope: int
    history: list[dict]  # [{date, value}, ...]
    forecast: list[dict]  # [{date, yhat, yhat_lower_80, yhat_upper_80, yhat_lower_95, yhat_upper_95}, ...]


class ForecastPoint(BaseModel):
    date: str
    value: float | None = None
    kind: str  # "actual" | "forecast"
    is_interpolated: bool = False
    yhat_lower: float | None = None   # 95% CI lower
    yhat_upper: float | None = None   # 95% CI upper
    yhat_lower_80: float | None = None
    yhat_upper_80: float | None = None


class ForecastResponse(BaseModel):
    project_id: int
    granularity: str
    model_used: str
    horizon_months: int
    trend: str
    reduction_warning: str
    compliance_gap_preview: dict
    points: list[ForecastPoint]
    echarts: dict
    data_sources: list[str]
    data_quality: dict = {}
    interpolation_count: int = 0
    outlier_count: int = 0
    # New fields for richer forecasting
    sub_item_forecasts: list[SubItemForecast] = []
    debug_info: dict = {}
    historical_max: float | None = None
    historical_avg: float | None = None
    scope_ratio: dict = {}  # {scope1_pct, scope2_pct}


class ForecastDebugResponse(BaseModel):
    """Full debug snapshot for a forecast run."""
    project_id: int
    model_used: str
    horizon_months: int
    model_input: dict  # historical stats, data quality, preprocessed data summary
    model_output: dict  # raw forecast values, CI bounds, constraints applied
    confidence_intervals: dict  # 80%/95% CI details per horizon step
    constraints: dict  # cap applied, scope ratio enforced
    warnings: list[str]  # all triggered warnings with conditions
    trace: list[str]  # step-by-step log
