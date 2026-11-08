from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ProjectBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    organization: str = Field(..., min_length=1, max_length=255)
    boundary: str = Field(..., min_length=1, max_length=255)
    boundary_method: str = Field(..., min_length=1, max_length=64)
    base_year: int = Field(..., ge=1990, le=2100)
    report_year: int = Field(..., ge=1990, le=2100)
    period_start: date | None = None
    period_end: date | None = None
    standard: str = Field(..., min_length=1, max_length=128)
    calculation_profile: Literal["AUTO", "ISO14064", "JS_T303"] = "AUTO"
    industry: str = Field(..., min_length=1, max_length=128)


class ProjectCreate(ProjectBase):
    pass


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    organization: str | None = Field(default=None, min_length=1, max_length=255)
    boundary: str | None = Field(default=None, min_length=1, max_length=255)
    boundary_method: str | None = Field(default=None, min_length=1, max_length=64)
    base_year: int | None = Field(default=None, ge=1990, le=2100)
    report_year: int | None = Field(default=None, ge=1990, le=2100)
    period_start: date | None = None
    period_end: date | None = None
    standard: str | None = Field(default=None, min_length=1, max_length=128)
    calculation_profile: Literal["AUTO", "ISO14064", "JS_T303"] | None = None
    industry: str | None = Field(default=None, min_length=1, max_length=128)


class ProjectRead(ProjectBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
