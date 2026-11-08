from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class NaturalGasTimeseriesCreate(BaseModel):
    period_type: str = Field(default="month", pattern=r"^(day|month|year)$")
    period_start: date
    period_end: date
    activity_data: float = Field(ge=0)
    activity_unit: str = Field(default="Nm3", max_length=32)
    factor: float = Field(ge=0)
    factor_unit: str = Field(default="kgCO2e/Nm3", max_length=64)
    factor_source: str = Field(default="JS/T 303-2026", max_length=255)
    gwp: float = Field(default=1.0, ge=0)
    gas: str = Field(default="CO2", max_length=32)
    co2e: float | None = Field(default=None, ge=0)
    scope: int = Field(default=1, ge=1, le=3)
    iso_category_code: str = Field(default="1.1", max_length=16)
    data_quality: str = Field(default="measured", max_length=16)
    source_system: str | None = Field(default=None, max_length=64)
    notes: str | None = Field(default=None, max_length=500)


class NaturalGasTimeseriesRead(NaturalGasTimeseriesCreate):
    co2e: float = Field(ge=0)
    id: int
    project_id: int
    created_at: datetime
    updated_at: datetime


class PurchasedElectricityTimeseriesCreate(BaseModel):
    period_type: str = Field(default="month", pattern=r"^(day|month|year)$")
    period_start: date
    period_end: date
    electricity_consumption: float = Field(ge=0)
    electricity_unit: str = Field(default="kWh", max_length=32)
    is_green_electricity: bool = False
    green_power_ratio: float = Field(default=0.0, ge=0, le=1)
    factor: float = Field(ge=0)
    factor_unit: str = Field(default="tCO2e/MWh", max_length=64)
    factor_source: str = Field(default="JS/T 303-2026", max_length=255)
    gwp: float = Field(default=1.0, ge=0)
    gas: str = Field(default="CO2", max_length=32)
    co2e: float | None = Field(default=None, ge=0)
    scope: int = Field(default=2, ge=1, le=3)
    iso_category_code: str = Field(default="2.1", max_length=16)
    consumption_type: str = Field(default="purchased", max_length=16)
    data_quality: str = Field(default="measured", max_length=16)
    source_system: str | None = Field(default=None, max_length=64)
    notes: str | None = Field(default=None, max_length=500)


class PurchasedElectricityTimeseriesRead(PurchasedElectricityTimeseriesCreate):
    co2e: float = Field(ge=0)
    id: int
    project_id: int
    created_at: datetime
    updated_at: datetime


class NaturalGasTimeseriesListResponse(BaseModel):
    items: list[NaturalGasTimeseriesRead]


class PurchasedElectricityTimeseriesListResponse(BaseModel):
    items: list[PurchasedElectricityTimeseriesRead]
