from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.natural_gas_timeseries import NaturalGasTimeseries
from app.models.project import Project
from app.models.purchased_electricity_timeseries import PurchasedElectricityTimeseries
from app.schemas.timeseries import (
    NaturalGasTimeseriesCreate,
    NaturalGasTimeseriesListResponse,
    NaturalGasTimeseriesRead,
    PurchasedElectricityTimeseriesCreate,
    PurchasedElectricityTimeseriesListResponse,
    PurchasedElectricityTimeseriesRead,
)

router = APIRouter(prefix="/timeseries", tags=["timeseries"])


def _ensure_project_exists(db: Session, project_id: int) -> None:
    p = db.query(Project.id).filter(Project.id == project_id, Project.is_deleted == False).first()
    if not p:
        raise HTTPException(status_code=404, detail="项目不存在")


def _normalize_electricity_to_mwh(value: float, unit: str) -> float:
    u = (unit or "").strip().lower()
    if u in {"kwh", "千瓦时"}:
        return value / 1000.0
    return value


def _to_tco2e(raw_value: float, factor_unit: str) -> float:
    fu = (factor_unit or "").strip().lower()
    if "kg" in fu:
        return raw_value / 1000.0
    return raw_value


def _calc_natural_gas_co2e(activity_data: float, factor: float, gwp: float, factor_unit: str) -> float:
    raw = float(activity_data or 0.0) * float(factor or 0.0) * float(gwp or 1.0)
    return round(max(_to_tco2e(raw, factor_unit), 0.0), 6)


def _calc_purchased_electricity_co2e(
    electricity_consumption: float,
    electricity_unit: str,
    factor: float,
    gwp: float,
    factor_unit: str,
    is_green_electricity: bool,
    green_power_ratio: float,
) -> float:
    mwh = _normalize_electricity_to_mwh(float(electricity_consumption or 0.0), electricity_unit)
    raw = mwh * float(factor or 0.0) * float(gwp or 1.0)
    co2e = _to_tco2e(raw, factor_unit)
    if is_green_electricity:
        ratio = min(max(float(green_power_ratio or 0.0), 0.0), 1.0)
        co2e = co2e * (1.0 - ratio)
    return round(max(co2e, 0.0), 6)


@router.post("/natural-gas/{project_id}", response_model=NaturalGasTimeseriesRead)
def create_natural_gas_timeseries(project_id: int, payload: NaturalGasTimeseriesCreate, db: Session = Depends(get_db)) -> NaturalGasTimeseriesRead:
    _ensure_project_exists(db, project_id)
    exists = (
        db.query(NaturalGasTimeseries)
        .filter(
            NaturalGasTimeseries.project_id == project_id,
            NaturalGasTimeseries.period_type == payload.period_type,
            NaturalGasTimeseries.period_start == payload.period_start,
        )
        .first()
    )
    if exists:
        raise HTTPException(status_code=400, detail="该周期天然气时序数据已存在")

    data = payload.model_dump()
    data["co2e"] = _calc_natural_gas_co2e(
        activity_data=data["activity_data"],
        factor=data["factor"],
        gwp=data.get("gwp", 1.0),
        factor_unit=data.get("factor_unit", ""),
    )

    row = NaturalGasTimeseries(project_id=project_id, **data)
    db.add(row)
    db.commit()
    db.refresh(row)
    return NaturalGasTimeseriesRead(
        id=row.id,
        project_id=row.project_id,
        period_type=row.period_type,
        period_start=row.period_start,
        period_end=row.period_end,
        activity_data=row.activity_data,
        activity_unit=row.activity_unit,
        factor=row.factor,
        factor_unit=row.factor_unit,
        factor_source=row.factor_source,
        gwp=row.gwp,
        gas=row.gas,
        co2e=row.co2e,
        scope=row.scope,
        iso_category_code=row.iso_category_code,
        data_quality=row.data_quality,
        source_system=row.source_system,
        notes=row.notes,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/natural-gas/{project_id}", response_model=NaturalGasTimeseriesListResponse)
def list_natural_gas_timeseries(
    project_id: int,
    period_type: str | None = None,
    year: int | None = Query(None, ge=2000, le=2100),
    db: Session = Depends(get_db),
) -> NaturalGasTimeseriesListResponse:
    _ensure_project_exists(db, project_id)
    q = db.query(NaturalGasTimeseries).filter(NaturalGasTimeseries.project_id == project_id)
    if period_type:
        q = q.filter(NaturalGasTimeseries.period_type == period_type)
    if year is not None:
        q = q.filter(func.year(NaturalGasTimeseries.period_start) == year)
    rows = q.order_by(NaturalGasTimeseries.period_start.asc(), NaturalGasTimeseries.id.asc()).all()
    items = [
        NaturalGasTimeseriesRead(
            id=r.id,
            project_id=r.project_id,
            period_type=r.period_type,
            period_start=r.period_start,
            period_end=r.period_end,
            activity_data=r.activity_data,
            activity_unit=r.activity_unit,
            factor=r.factor,
            factor_unit=r.factor_unit,
            factor_source=r.factor_source,
            gwp=r.gwp,
            gas=r.gas,
            co2e=r.co2e,
            scope=r.scope,
            iso_category_code=r.iso_category_code,
            data_quality=r.data_quality,
            source_system=r.source_system,
            notes=r.notes,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rows
    ]
    return NaturalGasTimeseriesListResponse(items=items)


@router.delete("/natural-gas/{record_id}")
def delete_natural_gas_timeseries(record_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    row = db.query(NaturalGasTimeseries).filter(NaturalGasTimeseries.id == record_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="记录不存在")
    db.delete(row)
    db.commit()
    return {"message": "已删除"}


@router.post("/purchased-electricity/{project_id}", response_model=PurchasedElectricityTimeseriesRead)
def create_purchased_electricity_timeseries(project_id: int, payload: PurchasedElectricityTimeseriesCreate, db: Session = Depends(get_db)) -> PurchasedElectricityTimeseriesRead:
    _ensure_project_exists(db, project_id)
    exists = (
        db.query(PurchasedElectricityTimeseries)
        .filter(
            PurchasedElectricityTimeseries.project_id == project_id,
            PurchasedElectricityTimeseries.period_type == payload.period_type,
            PurchasedElectricityTimeseries.period_start == payload.period_start,
        )
        .first()
    )
    if exists:
        raise HTTPException(status_code=400, detail="该周期外购电时序数据已存在")

    data = payload.model_dump()
    data["co2e"] = _calc_purchased_electricity_co2e(
        electricity_consumption=data["electricity_consumption"],
        electricity_unit=data.get("electricity_unit", "kWh"),
        factor=data["factor"],
        gwp=data.get("gwp", 1.0),
        factor_unit=data.get("factor_unit", ""),
        is_green_electricity=bool(data.get("is_green_electricity", False)),
        green_power_ratio=float(data.get("green_power_ratio", 0.0) or 0.0),
    )

    row = PurchasedElectricityTimeseries(project_id=project_id, **data)
    db.add(row)
    db.commit()
    db.refresh(row)
    return PurchasedElectricityTimeseriesRead(
        id=row.id,
        project_id=row.project_id,
        period_type=row.period_type,
        period_start=row.period_start,
        period_end=row.period_end,
        electricity_consumption=row.electricity_consumption,
        electricity_unit=row.electricity_unit,
        is_green_electricity=row.is_green_electricity,
        green_power_ratio=row.green_power_ratio,
        factor=row.factor,
        factor_unit=row.factor_unit,
        factor_source=row.factor_source,
        gwp=row.gwp,
        gas=row.gas,
        co2e=row.co2e,
        scope=row.scope,
        iso_category_code=row.iso_category_code,
        consumption_type=row.consumption_type,
        data_quality=row.data_quality,
        source_system=row.source_system,
        notes=row.notes,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/purchased-electricity/{project_id}", response_model=PurchasedElectricityTimeseriesListResponse)
def list_purchased_electricity_timeseries(
    project_id: int,
    period_type: str | None = None,
    year: int | None = Query(None, ge=2000, le=2100),
    db: Session = Depends(get_db),
) -> PurchasedElectricityTimeseriesListResponse:
    _ensure_project_exists(db, project_id)
    q = db.query(PurchasedElectricityTimeseries).filter(PurchasedElectricityTimeseries.project_id == project_id)
    if period_type:
        q = q.filter(PurchasedElectricityTimeseries.period_type == period_type)
    if year is not None:
        q = q.filter(func.year(PurchasedElectricityTimeseries.period_start) == year)
    rows = q.order_by(PurchasedElectricityTimeseries.period_start.asc(), PurchasedElectricityTimeseries.id.asc()).all()
    items = [
        PurchasedElectricityTimeseriesRead(
            id=r.id,
            project_id=r.project_id,
            period_type=r.period_type,
            period_start=r.period_start,
            period_end=r.period_end,
            electricity_consumption=r.electricity_consumption,
            electricity_unit=r.electricity_unit,
            is_green_electricity=r.is_green_electricity,
            green_power_ratio=r.green_power_ratio,
            factor=r.factor,
            factor_unit=r.factor_unit,
            factor_source=r.factor_source,
            gwp=r.gwp,
            gas=r.gas,
            co2e=r.co2e,
            scope=r.scope,
            iso_category_code=r.iso_category_code,
            consumption_type=r.consumption_type,
            data_quality=r.data_quality,
            source_system=r.source_system,
            notes=r.notes,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rows
    ]
    return PurchasedElectricityTimeseriesListResponse(items=items)


@router.delete("/purchased-electricity/{record_id}")
def delete_purchased_electricity_timeseries(record_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    row = db.query(PurchasedElectricityTimeseries).filter(PurchasedElectricityTimeseries.id == record_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="记录不存在")
    db.delete(row)
    db.commit()
    return {"message": "已删除"}
