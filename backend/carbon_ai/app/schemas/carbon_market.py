from datetime import datetime
from pydantic import BaseModel, Field


class QuotaGapRequest(BaseModel):
    allocation_method: str = Field(default="benchmark", min_length=1, max_length=64)
    snapshot_id: int | None = None


class QuotaGapResponse(BaseModel):
    total_emission: float
    free_quota: float
    quota_gap: float
    record_id: int | None = None


class OptimizeRequest(BaseModel):
    carbon_price: float = Field(..., gt=0)
    ccer_price: float = Field(..., gt=0)
    green_electricity_price: float = Field(..., gt=0)
    ccer_max_ratio: float = Field(default=0.30, ge=0.0, le=1.0)
    green_power_max_ratio: float = Field(default=0.20, ge=0.0, le=1.0)
    notes: str | None = None


class OptimizeResponse(BaseModel):
    optimal_plan: dict[str, float]
    total_cost: float
    record_id: int
    saving_compared_to_full_quota: float | None = None


class ComplianceSummaryResponse(BaseModel):
    project_id: int
    total_emission: float
    free_quota: float
    quota_gap: float
    ccer_offset_limit: float
    green_power_offset_limit: float


class CompliancePlanItem(BaseModel):
    name: str
    quota_buy: float
    ccer_buy: float
    green_power_buy: float
    total_cost: float
    notes: str = ""


class ComplianceSimulateRequest(BaseModel):
    allocation_method: str = Field(default="benchmark", min_length=1, max_length=64)
    carbon_price: float = Field(default=85.0, gt=0)
    ccer_price: float = Field(default=60.0, gt=0)
    green_electricity_price: float = Field(default=70.0, gt=0)
    ccer_max_ratio: float = Field(default=0.30, ge=0.0, le=1.0)
    green_power_max_ratio: float = Field(default=0.20, ge=0.0, le=1.0)
    save_snapshot: bool = Field(default=False, description="是否保存为快照")
    snapshot_name: str | None = Field(default=None, max_length=255)


class ComplianceSimulateResponse(BaseModel):
    summary: ComplianceSummaryResponse
    plans: list[CompliancePlanItem]
    recommended_plan: str
    recommended_saving_ratio: float
    snapshot_id: int | None = None


class ComplianceReportResponse(BaseModel):
    file_path: str
    snapshot_id: int | None = None


class SnapshotCreateRequest(BaseModel):
    snapshot_name: str = Field(..., min_length=1, max_length=255)
    allocation_method: str = Field(..., min_length=1, max_length=64)
    carbon_price: float = Field(..., gt=0)
    ccer_price: float = Field(..., gt=0)
    green_electricity_price: float = Field(..., gt=0)
    ccer_max_ratio: float = Field(default=0.30, ge=0.0, le=1.0)
    green_power_max_ratio: float = Field(default=0.20, ge=0.0, le=1.0)


class SnapshotResponse(BaseModel):
    id: int
    snapshot_name: str
    allocation_method: str
    carbon_price: float
    ccer_price: float
    green_electricity_price: float
    total_emission: float
    free_quota: float
    quota_gap: float
    recommended_plan: str
    recommended_saving_ratio: float
    is_final: bool
    created_at: datetime
    created_by: int | None


class SnapshotListResponse(BaseModel):
    snapshots: list[SnapshotResponse]


class MarketPriceConfigCreateRequest(BaseModel):
    price_type: str = Field(..., min_length=1, max_length=32)
    price: float = Field(..., gt=0)
    currency: str = Field(default="CNY", max_length=16)
    effective_date: datetime
    expiry_date: datetime | None = None
    source: str | None = Field(None, max_length=255)
    notes: str | None = None


class MarketPriceConfigResponse(BaseModel):
    id: int
    price_type: str
    price: float
    currency: str
    effective_date: datetime
    expiry_date: datetime | None
    is_active: bool
    source: str | None
    notes: str | None
    created_at: datetime
    created_by: int | None


class MarketPriceConfigListResponse(BaseModel):
    configs: list[MarketPriceConfigResponse]


class ComplianceHistoryResponse(BaseModel):
    id: int
    allocation_method: str
    carbon_price: float
    ccer_price: float
    green_electricity_price: float
    total_emission: float
    quota_gap: float
    optimal_cost: float
    is_final: bool
    created_at: datetime
    created_by: int | None
    created_by_username: str | None = None


class ComplianceHistoryListResponse(BaseModel):
    records: list[ComplianceHistoryResponse]
    total: int


class AllowanceAccountCreateRequest(BaseModel):
    account_name: str = Field(..., min_length=1, max_length=255)
    account_code: str = Field(..., min_length=1, max_length=64)
    balance_quota: float = Field(default=0.0, ge=0.0)
    ccer_balance: float = Field(default=0.0, ge=0.0)
    notes: str | None = None


class AllowanceAccountResponse(BaseModel):
    id: int
    project_id: int
    account_name: str
    account_code: str
    balance_quota: float
    ccer_balance: float
    notes: str | None
    created_at: datetime


class AllowanceAccountListResponse(BaseModel):
    accounts: list[AllowanceAccountResponse]
    total: int


class AllowanceTxnCreateRequest(BaseModel):
    account_id: int | None = None
    txn_type: str = Field(..., min_length=1, max_length=32)
    instrument: str = Field(..., min_length=1, max_length=32)
    quantity: float = Field(..., gt=0)
    unit_price: float = Field(..., ge=0)
    txn_date: datetime
    reference_no: str | None = Field(default=None, max_length=128)
    notes: str | None = None


class AllowanceTxnResponse(BaseModel):
    id: int
    project_id: int
    account_id: int | None
    txn_type: str
    instrument: str
    quantity: float
    unit_price: float
    total_amount: float
    txn_date: datetime
    reference_no: str | None
    notes: str | None
    created_by: int | None
    created_at: datetime


class AllowanceTxnListResponse(BaseModel):
    transactions: list[AllowanceTxnResponse]
    total: int


class ComplianceParamVersionCreateRequest(BaseModel):
    version_name: str = Field(..., min_length=1, max_length=128)
    allocation_method: str = Field(default="benchmark", min_length=1, max_length=64)
    carbon_price: float = Field(..., gt=0)
    ccer_price: float = Field(..., gt=0)
    green_electricity_price: float = Field(..., gt=0)
    ccer_max_ratio: float = Field(default=0.30, ge=0.0, le=1.0)
    green_power_max_ratio: float = Field(default=0.20, ge=0.0, le=1.0)
    is_active: bool = True
    notes: str | None = None


class ComplianceParamVersionResponse(BaseModel):
    id: int
    project_id: int
    version_name: str
    allocation_method: str
    carbon_price: float
    ccer_price: float
    green_electricity_price: float
    ccer_max_ratio: float
    green_power_max_ratio: float
    is_active: bool
    notes: str | None
    created_at: datetime
    created_by: int | None


class ComplianceParamVersionListResponse(BaseModel):
    versions: list[ComplianceParamVersionResponse]
    total: int


# ---------------------------------------------------------------------------
# Real-time carbon market price
# ---------------------------------------------------------------------------
class MarketPriceResponse(BaseModel):
    symbol: str = ""
    price: float = 0.0
    price_date: str = ""  # YYYY-MM-DD
    open_price: float = 0.0
    high_price: float = 0.0
    low_price: float = 0.0
    close_price: float = 0.0
    volume: float = 0.0  # tonnes
    turnover: float = 0.0  # CNY
    change_pct: float = 0.0
    source: str = ""
    fetched_at: str = ""
    cached: bool = False
    fallback_layer: int = 0  # 0=live scraper, 1=AKShare, 2=offline benchmark


class MarketPriceDebugResponse(BaseModel):
    source: str = ""
    success: bool = True
    price: float = 0.0
    price_date: str = ""
    volume: float = 0.0
    turnover: float = 0.0
    fallback_layer: int = 0
    trace: list[str] = Field(default_factory=list)
    snapshot: MarketPriceResponse | None = None


# ---------------------------------------------------------------------------
# EUA (European Union Allowance) real-time carbon futures price
# ---------------------------------------------------------------------------
class EUAMarketPriceResponse(BaseModel):
    symbol: str = "EUA"
    price: float = 0.0
    price_date: str = ""
    open_price: float = 0.0
    high_price: float = 0.0
    low_price: float = 0.0
    close_price: float = 0.0
    volume: float = 0.0
    turnover: float = 0.0
    change_pct: float = 0.0
    source: str = ""
    fetched_at: str = ""
    cached: bool = False
    fallback_layer: int = 0  # 0=live scraper, 1=stale cache, 2=offline benchmark
    settlement_date: str = ""  # EUA futures settlement date


class EUAMarketPriceDebugResponse(BaseModel):
    source: str = ""
    success: bool = True
    price: float = 0.0
    price_date: str = ""
    volume: float = 0.0
    turnover: float = 0.0
    fallback_layer: int = 0
    settlement_date: str = ""
    trace: list[str] = Field(default_factory=list)
    snapshot: EUAMarketPriceResponse | None = None
