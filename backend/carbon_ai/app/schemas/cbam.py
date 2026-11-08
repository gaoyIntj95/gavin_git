from datetime import datetime
from pydantic import BaseModel, Field


class CbamExtractRequest(BaseModel):
    batch_id: int | None = None
    product_name: str = Field(..., min_length=1, max_length=255)
    product_category: str | None = Field(None, max_length=128)
    product_quantity: float = Field(..., gt=0)
    unit: str = Field(..., min_length=1, max_length=64)
    eu_carbon_price: float = Field(default=85.0, gt=0)
    eu_price_date: datetime | None = None
    footprint_scope: str | None = Field(None, max_length=64)
    notes: str | None = None


class CbamExtractResponse(BaseModel):
    id: int
    carbon_footprint: float
    carbon_tariff: float
    status: str


class CbamUpdateRequest(BaseModel):
    product_category: str | None = Field(None, max_length=128)
    product_quantity: float | None = Field(None, gt=0)
    eu_carbon_price: float | None = Field(None, gt=0)
    eu_price_date: datetime | None = None
    footprint_scope: str | None = Field(None, max_length=64)
    status: str | None = Field(default=None, max_length=32)
    notes: str | None = None


class CbamItemResponse(BaseModel):
    id: int
    product_name: str
    product_category: str | None
    product_quantity: float
    unit: str
    carbon_footprint: float
    footprint_scope: str | None
    eu_carbon_price: float
    eu_price_date: datetime | None
    carbon_tariff: float
    currency: str
    status: str
    notes: str | None
    created_at: datetime
    created_by: int | None
    created_by_username: str | None = None


class CbamListResponse(BaseModel):
    items: list[CbamItemResponse]
    total: int


class CbamTemplateResponse(BaseModel):
    file_path: str
    batch_id: int | None = None


class CbamSummaryItem(BaseModel):
    product_name: str
    product_category: str | None
    product_quantity: float
    unit: str
    carbon_footprint: float
    eu_carbon_price: float
    carbon_tariff: float


class CbamSummaryResponse(BaseModel):
    project_id: int
    batch_id: int | None = None
    total_products: int
    total_quantity: float
    total_carbon_tariff: float
    items: list[CbamSummaryItem]


class CbamBatchCreateRequest(BaseModel):
    batch_name: str = Field(..., min_length=1, max_length=255)
    declaration_period_start: datetime
    declaration_period_end: datetime
    notes: str | None = None


class CbamBatchResponse(BaseModel):
    id: int
    project_id: int
    batch_name: str
    batch_number: str
    declaration_period_start: datetime
    declaration_period_end: datetime
    total_products: int
    total_quantity: float
    total_tariff: float
    status: str
    submitted_at: datetime | None
    reviewed_at: datetime | None
    reviewed_by: int | None
    review_comment: str | None
    created_at: datetime
    created_by: int | None
    updated_at: datetime


class CbamBatchListResponse(BaseModel):
    batches: list[CbamBatchResponse]
    total: int


class CbamExportPackageResponse(BaseModel):
    package_path: str
    batch_id: int
    batch_name: str


class CbamReviewRequest(BaseModel):
    status: str = Field(..., pattern=r"^(approved|rejected|needs_revision)$")
    review_comment: str | None = Field(None, max_length=512)


class CbamReviewResponse(BaseModel):
    success: bool
    message: str


class CbamEvidenceUploadRequest(BaseModel):
    evidence_type: str = Field(..., min_length=1, max_length=64)
    evidence_name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None


class CbamEvidenceResponse(BaseModel):
    id: int
    evidence_type: str
    evidence_name: str
    file_path: str | None
    file_size: int
    description: str | None
    uploaded_at: datetime
    uploaded_by: int | None
