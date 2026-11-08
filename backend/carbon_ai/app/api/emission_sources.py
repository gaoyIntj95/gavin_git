from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.database import get_db
from app.models.evidence_record import EvidenceRecord
from app.models.emission_source import EmissionSource
from app.models.project import Project
from app.models.uncertainty_assessment import UncertaintyAssessment
from app.schemas.emission_source import (
    BatchImportResult,
    CalculationResult,
    EmissionSourceCreate,
    EmissionSourceRead,
    ValidationResult,
)
from app.services.calculation_service import (
    calculate_co2e,
    calculate_central_fire_extinguisher_total_co2e,
    calculate_portable_fire_extinguisher_total_co2e,
    calculate_refrigerant_fugitive_total_co2e,
    calculate_scope1_diesel_total_co2e,
    calculate_scope1_gasoline_total_co2e,
    calculate_scope1_natural_gas_total_co2e,
    calculate_project_totals,
    infer_iso_category,
    normalize_ghg_category,
    normalize_gas_and_gwp,
    normalize_source_classification,
    resolve_project_calculation_profile,
    sync_project_uncertainty_assessments,
    validate_project_sources,
)
from app.services.factor_service import match_factor, match_factor_optional
from app.services.project_service import get_project_or_404
from app.utils.excel_utils import parse_emission_source_file


router = APIRouter(prefix="/projects/{project_id}/emission-sources", tags=["emission-sources"])
calc_router = APIRouter(prefix="/projects", tags=["calculation"])
SCOPE1_COMBUSTION_CATEGORIES = {"汽油", "柴油", "天然气"}


def _get_source_or_404(db: Session, project_id: int, source_id: int) -> EmissionSource:
    source = (
        db.query(EmissionSource)
        .options(selectinload(EmissionSource.uncertainties))
        .options(selectinload(EmissionSource.evidences))
        .filter(EmissionSource.project_id == project_id)
        .filter(EmissionSource.id == source_id)
        .first()
    )
    if not source:
        raise HTTPException(status_code=404, detail="排放源不存在")
    return source


def _is_green_purchased_electricity(emission_class: str, energy_type: str, consumption_type: str, green_flag: bool) -> bool:
    return (
        emission_class == "indirect"
        and energy_type == "electricity"
        and consumption_type == "purchased"
        and green_flag
    )


def _scope_for_profile(profile: str, iso_major: int, inferred_scope: int) -> int:
    if profile != "ISO14064":
        return inferred_scope
    if iso_major == 1:
        return 1
    if iso_major == 2:
        return 2
    return 3


def _calculate_source_co2e(source: EmissionSource, *, green_electricity_case: bool) -> float:
    merged_text = f"{source.category} {source.name}".strip().lower()
    if "制冷剂" in merged_text or "冷媒" in merged_text or "refrigerant" in merged_text:
        total, _parts = calculate_refrigerant_fugitive_total_co2e(
            source.activity_data,
            factor=source.factor,
            gwp=source.gwp,
        )
        return total
    if "灭火器" in merged_text:
        if "便携式灭火器" in merged_text or "portable extinguisher" in merged_text:
            total, _parts = calculate_portable_fire_extinguisher_total_co2e(
                source.activity_data,
                gwp=(source.gwp if source.gwp > 0 else 1.0),
            )
            return total
        if "中央灭火系统" in merged_text or "central extinguishing system" in merged_text:
            total, _parts = calculate_central_fire_extinguisher_total_co2e(source.activity_data)
            return total
    if source.emission_class == "direct" and source.energy_type == "fuel" and (
        "汽油" in merged_text or "gasoline" in merged_text
    ):
        total, _parts = calculate_scope1_gasoline_total_co2e(source.activity_data)
        return total
    if source.emission_class == "direct" and source.energy_type == "fuel" and (
        "柴油" in merged_text or "diesel" in merged_text
    ):
        total, _parts = calculate_scope1_diesel_total_co2e(source.activity_data)
        return total
    if source.emission_class == "direct" and source.energy_type == "fuel" and (
        "天然气" in merged_text or "natural gas" in merged_text
    ):
        total, _parts = calculate_scope1_natural_gas_total_co2e(source.activity_data)
        return total
    return calculate_co2e(
        source.activity_data,
        source.factor,
        source.gwp,
        is_green_electricity=green_electricity_case,
    )


def _build_scope1_combustion_factor(
    *,
    db: Session,
    project: Project,
    category: str,
    emission_class: str,
    energy_type: str,
    consumption_type: str,
) -> tuple[float, str] | None:
    if emission_class != "direct" or energy_type != "fuel":
        return None
    if category not in SCOPE1_COMBUSTION_CATEGORIES:
        return None

    gas_gwp = {"CO2": 1.0, "CH4": 27.9, "N2O": 273.0}
    total_factor = 0.0
    found_parts: list[str] = []
    missing_parts: list[str] = []

    for gas, gwp in gas_gwp.items():
        matched = match_factor_optional(
            db,
            category,
            industry=project.industry,
            emission_class=emission_class,
            energy_type=energy_type,
            consumption_type=consumption_type,
            gas=gas,
        )
        if matched is None:
            missing_parts.append(gas)
            continue
        value, _source = matched
        co2e_factor = float(value) * gwp
        total_factor += co2e_factor
        found_parts.append(f"{gas}:{value}*{gwp}")

    if not found_parts:
        return None

    source_text = "自动合并燃烧因子(CO2+CH4+N2O)"
    if missing_parts:
        source_text += f"，缺失:{'/'.join(missing_parts)}按0处理"
    return total_factor, source_text


def _append_uncertainties(source: EmissionSource, items) -> None:
    if not items:
        return
    for item in items:
        source.uncertainties.append(
            UncertaintyAssessment(
                emission_source_name=source.category,
                facility=(item.facility or source.name),
                activity_data_category=item.activity_data_category,
                factor_category=item.factor_category,
                activity_level=None,
                factor_level=None,
                average_score=None,
                emission_amount=0.0,
                emission_share=0.0,
                weighted_score=0.0,
                notes=item.notes,
            )
        )


def _append_evidences(source: EmissionSource, items) -> None:
    if not items:
        return
    for item in items:
        source.evidences.append(
            EvidenceRecord(
                evidence_type=item.evidence_type,
                file_path=item.file_path,
                description=item.description,
                period_start=item.period_start,
                period_end=item.period_end,
            )
        )


def _apply_payload_to_source(
    *,
    db: Session,
    project: Project,
    profile: str,
    project_id: int,
    source: EmissionSource,
    payload: EmissionSourceCreate,
) -> None:
    normalized = normalize_source_classification(
        scope=payload.scope,
        category=payload.category,
        name=payload.name,
        emission_class=payload.emission_class,
        energy_type=payload.energy_type,
        consumption_type=payload.consumption_type,
        is_green_electricity=payload.is_green_electricity,
    )
    emission_class = str(normalized["emission_class"])
    energy_type = str(normalized["energy_type"])
    consumption_type = str(normalized["consumption_type"])
    green_flag = bool(normalized["is_green_electricity"])
    inferred_scope = int(normalized["inferred_scope"])
    iso_major, iso_code = infer_iso_category(
        category=payload.category,
        name=payload.name,
        emission_class=emission_class,
        energy_type=energy_type,
    )
    scope = _scope_for_profile(profile, iso_major, inferred_scope)

    gas, gwp = normalize_gas_and_gwp(payload.gas, payload.gwp)
    manual_factor = payload.factor
    manual_factor_source = payload.factor_source
    if manual_factor is not None:
        factor = float(manual_factor)
        factor_source = manual_factor_source or "手动输入"
    else:
        combined = _build_scope1_combustion_factor(
            db=db,
            project=project,
            category=payload.category,
            emission_class=emission_class,
            energy_type=energy_type,
            consumption_type=consumption_type,
        )
        if combined is not None:
            factor, factor_source = combined
        else:
            factor, factor_source = match_factor(
                db,
                payload.category,
                industry=project.industry,
                emission_class=emission_class,
                energy_type=energy_type,
                consumption_type=consumption_type,
                gas=gas,
            )

    green_case = _is_green_purchased_electricity(emission_class, energy_type, consumption_type, green_flag)
    if green_case:
        factor = 0.0

    source.project_id = project_id
    source.scope = scope
    source.category = payload.category
    source.name = payload.name
    source.activity_data = payload.activity_data
    source.unit = payload.unit
    source.factor = factor
    source.factor_source = factor_source or "自动匹配"
    source.gas = gas
    source.gwp = gwp
    source.emission_class = emission_class
    source.energy_type = energy_type
    source.consumption_type = consumption_type
    source.is_green_electricity = green_flag
    source.iso_category_major = iso_major
    source.iso_category_code = iso_code
    source.ghg_category = normalize_ghg_category(
        payload.ghg_category,
        iso_category_major=iso_major,
        iso_category_code=iso_code,
        energy_type=energy_type,
    )
    source.is_removal = payload.is_removal
    source.is_storage = payload.is_storage
    source.period_start = payload.period_start or project.period_start
    source.period_end = payload.period_end or project.period_end
    source.notes = payload.notes
    source.co2e = _calculate_source_co2e(source, green_electricity_case=green_case)

    source.uncertainties.clear()
    source.evidences.clear()
    _append_uncertainties(source, payload.uncertainties)
    _append_evidences(source, payload.evidences)


@router.post("", response_model=EmissionSourceRead, status_code=201)
def add_emission_source(
    project_id: int,
    payload: EmissionSourceCreate,
    db: Session = Depends(get_db),
) -> EmissionSource:
    project = get_project_or_404(db, project_id)
    profile = resolve_project_calculation_profile(project.standard, project.calculation_profile)
    source = EmissionSource()
    _apply_payload_to_source(
        db=db,
        project=project,
        profile=profile,
        project_id=project_id,
        source=source,
        payload=payload,
    )

    db.add(source)
    db.flush()
    sync_project_uncertainty_assessments(db, project_id)
    db.commit()
    db.refresh(source)
    return source


@router.get("", response_model=list[EmissionSourceRead])
def list_emission_sources(
    project_id: int,
    scope: int | None = None,
    category: str | None = None,
    db: Session = Depends(get_db),
) -> list[EmissionSource]:
    get_project_or_404(db, project_id)
    sync_project_uncertainty_assessments(db, project_id)
    db.commit()
    query = (
        db.query(EmissionSource)
        .options(selectinload(EmissionSource.uncertainties))
        .options(selectinload(EmissionSource.evidences))
        .filter(EmissionSource.project_id == project_id)
    )
    if scope is not None:
        query = query.filter(EmissionSource.scope == scope)
    if category:
        query = query.filter(EmissionSource.category == category)
    sources = query.order_by(EmissionSource.created_at.desc()).all()

    # Backfill corrected formulas for historical records (e.g. fire extinguisher fugitive rows)
    # so frontend list reflects latest enterprise-calculation rules immediately.
    dirty = False
    for source in sources:
        green_case = _is_green_purchased_electricity(
            source.emission_class,
            source.energy_type,
            source.consumption_type,
            source.is_green_electricity,
        )
        expected = _calculate_source_co2e(source, green_electricity_case=green_case)
        if abs(float(source.co2e or 0.0) - float(expected or 0.0)) > 1e-9:
            source.co2e = expected
            dirty = True
    if dirty:
        db.commit()

    return sources


@router.get("/{source_id}", response_model=EmissionSourceRead)
def get_emission_source(
    project_id: int,
    source_id: int,
    db: Session = Depends(get_db),
) -> EmissionSource:
    get_project_or_404(db, project_id)
    source = _get_source_or_404(db, project_id, source_id)
    return source


@router.put("/{source_id}", response_model=EmissionSourceRead)
def update_emission_source(
    project_id: int,
    source_id: int,
    payload: EmissionSourceCreate,
    db: Session = Depends(get_db),
) -> EmissionSource:
    project = get_project_or_404(db, project_id)
    profile = resolve_project_calculation_profile(project.standard, project.calculation_profile)
    source = _get_source_or_404(db, project_id, source_id)

    _apply_payload_to_source(
        db=db,
        project=project,
        profile=profile,
        project_id=project_id,
        source=source,
        payload=payload,
    )
    db.flush()
    sync_project_uncertainty_assessments(db, project_id)
    db.commit()
    db.refresh(source)
    return source


@router.delete("/{source_id}")
def delete_emission_source(
    project_id: int,
    source_id: int,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    get_project_or_404(db, project_id)
    source = _get_source_or_404(db, project_id, source_id)
    db.delete(source)
    db.flush()
    sync_project_uncertainty_assessments(db, project_id)
    db.commit()
    return {"message": "排放源已删除"}


@router.post("/batch", response_model=BatchImportResult)
async def batch_import_emission_sources(
    project_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> BatchImportResult:
    project = get_project_or_404(db, project_id)
    profile = resolve_project_calculation_profile(project.standard, project.calculation_profile)
    file_suffix = Path(file.filename or "").suffix.lower()
    if file_suffix not in (".csv", ".xls", ".xlsx"):
        raise HTTPException(status_code=400, detail="仅支持 CSV / XLS / XLSX 文件上传")

    target_name = f"{project_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{file_suffix}"
    target_path = settings.upload_dir / target_name
    content = await file.read()
    target_path.write_bytes(content)

    try:
        items = parse_emission_source_file(target_path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    success_count = 0
    errors: list[str] = []
    for index, item in enumerate(items, start=1):
        try:
            normalized = normalize_source_classification(
                scope=int(item["scope"]),
                category=str(item["category"]),
                name=str(item["name"]),
                emission_class=item.get("emission_class"),
                energy_type=item.get("energy_type"),
                consumption_type=item.get("consumption_type"),
                is_green_electricity=bool(item.get("is_green_electricity")),
            )
            emission_class = str(normalized["emission_class"])
            energy_type = str(normalized["energy_type"])
            consumption_type = str(normalized["consumption_type"])
            green_flag = bool(normalized["is_green_electricity"])
            inferred_scope = int(normalized["inferred_scope"])

            iso_major, iso_code = infer_iso_category(
                category=str(item["category"]),
                name=str(item["name"]),
                emission_class=emission_class,
                energy_type=energy_type,
            )
            scope = _scope_for_profile(profile, iso_major, inferred_scope)

            item_gwp = item.get("gwp")
            parsed_gwp = None
            if item_gwp not in (None, ""):
                parsed_gwp = float(item_gwp)
            gas, gwp = normalize_gas_and_gwp(
                str(item.get("gas") or "CO2"),
                parsed_gwp,
            )
            combined = _build_scope1_combustion_factor(
                db=db,
                project=project,
                category=str(item["category"]),
                emission_class=emission_class,
                energy_type=energy_type,
                consumption_type=consumption_type,
            )
            if combined is not None:
                factor, factor_source = combined
            else:
                factor, factor_source = match_factor(
                    db,
                    str(item["category"]),
                    industry=project.industry,
                    emission_class=emission_class,
                    energy_type=energy_type,
                    consumption_type=consumption_type,
                    gas=gas,
                )

            green_case = _is_green_purchased_electricity(emission_class, energy_type, consumption_type, green_flag)
            if green_case:
                factor = 0.0

            source = EmissionSource(
                project_id=project_id,
                scope=scope,
                category=str(item["category"]),
                name=str(item["name"]),
                activity_data=float(item["activity_data"]),
                unit=str(item["unit"]),
                factor=float(factor),
                factor_source=str(factor_source or "自动匹配"),
                gas=gas,
                gwp=gwp,
                co2e=0.0,
                emission_class=emission_class,
                energy_type=energy_type,
                consumption_type=consumption_type,
                is_green_electricity=green_flag,
                iso_category_major=iso_major,
                iso_category_code=iso_code,
                is_removal=bool(item.get("is_removal", False)),
                is_storage=bool(item.get("is_storage", False)),
                period_start=item.get("period_start"),
                period_end=item.get("period_end"),
                notes=item.get("notes"),
            )
            source.co2e = _calculate_source_co2e(source, green_electricity_case=green_case)
            db.add(source)
            success_count += 1
        except Exception as exc:
            errors.append(f"第 {index} 行导入失败: {exc}")

    db.commit()
    sync_project_uncertainty_assessments(db, project_id)
    db.commit()
    return BatchImportResult(success_count=success_count, fail_count=len(errors), errors=errors)


@calc_router.post("/{project_id}/calculate", response_model=CalculationResult)
def calculate_project(project_id: int, db: Session = Depends(get_db)) -> CalculationResult:
    get_project_or_404(db, project_id)
    result = calculate_project_totals(db, project_id)
    return CalculationResult(**result)


@calc_router.post("/{project_id}/validate", response_model=ValidationResult)
def validate_project(project_id: int, db: Session = Depends(get_db)) -> ValidationResult:
    get_project_or_404(db, project_id)
    result = validate_project_sources(db, project_id)
    return ValidationResult(**result)

