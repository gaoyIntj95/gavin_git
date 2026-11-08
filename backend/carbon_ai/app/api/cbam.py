from pathlib import Path
from typing import Any
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.auth import get_current_user, require_admin
from app.core.config import settings
from app.core.database import get_db
from app.models.cbam_data import CbamData
from app.models.cbam_declaration_batch import CbamDeclarationBatch
from app.models.cbam_evidence import CbamEvidence
from app.schemas.carbon_market import (
    EUAMarketPriceDebugResponse,
    EUAMarketPriceResponse,
)
from app.schemas.cbam import (
    CbamBatchCreateRequest,
    CbamBatchListResponse,
    CbamBatchResponse,
    CbamEvidenceResponse,
    CbamEvidenceUploadRequest,
    CbamExtractRequest,
    CbamExtractResponse,
    CbamExportPackageResponse,
    CbamItemResponse,
    CbamListResponse,
    CbamReviewRequest,
    CbamReviewResponse,
    CbamSummaryItem,
    CbamSummaryResponse,
    CbamTemplateResponse,
    CbamUpdateRequest,
)
from app.services.eu_carbon_price_service import fetch_latest_price as fetch_eua_price
from app.services.calculation_service import calculate_project_totals
from app.services.cbam_service import (
    build_template_filename,
    estimate_cbam_metrics,
    generate_cbam_package,
    generate_cbam_template,
    summarize_cbam,
)
from app.services.cbam_audit_service import (
    auto_assign_batch_number,
    create_declaration_batch,
    generate_cbam_export_package,
    get_batch_cbam_items,
    get_project_cbam_batches,
    log_cbam_audit,
    validate_cbam_parameters,
)
from app.services.project_service import ensure_project_exists

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cbam", tags=["cbam"])


@router.get("/validate-batch/{batch_id}")
def validate_batch(
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> dict[str, Any]:
    batch = db.query(CbamDeclarationBatch).filter(CbamDeclarationBatch.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="batch not found")
    items = db.query(CbamData).filter(CbamData.batch_id == batch_id).all()
    errors: list[str] = []
    if not items:
        errors.append("batch has no items")
    if batch.declaration_period_end <= batch.declaration_period_start:
        errors.append("declaration period invalid")
    uncategorized = sum(1 for i in items if not (i.product_category or "").strip())
    if uncategorized > 0:
        errors.append(f"{uncategorized} items missing product_category")
    missing_scope = sum(1 for i in items if not (i.footprint_scope or "").strip())
    if missing_scope > 0:
        errors.append(f"{missing_scope} items missing footprint_scope")
    return {
        "batch_id": batch_id,
        "ok": len(errors) == 0,
        "errors": errors,
        "item_count": len(items),
    }


@router.post("/extract/{project_id}", response_model=CbamExtractResponse)
def extract_cbam_data(
    project_id: int,
    payload: CbamExtractRequest,
    db: Session = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> CbamExtractResponse:
    ensure_project_exists(db, project_id)
    totals = calculate_project_totals(db, project_id)

    carbon_footprint, carbon_tariff = estimate_cbam_metrics(
        total_emission=totals["total_emission"],
        product_quantity=payload.product_quantity,
        eu_carbon_price=payload.eu_carbon_price,
    )

    item = CbamData(
        project_id=project_id,
        batch_id=payload.batch_id,
        product_name=payload.product_name,
        product_category=payload.product_category,
        product_quantity=payload.product_quantity,
        unit=payload.unit,
        carbon_footprint=carbon_footprint,
        footprint_scope=payload.footprint_scope,
        eu_carbon_price=payload.eu_carbon_price,
        eu_price_date=payload.eu_price_date,
        carbon_tariff=carbon_tariff,
        status="draft",
        notes=payload.notes,
        created_by=current_user.id,
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    log_cbam_audit(
        db,
        project_id=project_id,
        action_type="extract_cbam_data",
        action_description=f"提取 CBAM 数据: {payload.product_name}",
        old_value=None,
        new_value={
            "product_name": payload.product_name,
            "carbon_footprint": carbon_footprint,
            "carbon_tariff": carbon_tariff,
        },
        created_by=current_user.id,
    )

    return CbamExtractResponse(
        id=item.id,
        carbon_footprint=carbon_footprint,
        carbon_tariff=carbon_tariff,
        status=item.status,
    )


@router.patch("/items/{item_id}", response_model=CbamItemResponse)
def update_cbam_item(
    item_id: int,
    payload: CbamUpdateRequest,
    db: Session = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> CbamItemResponse:
    item = db.query(CbamData).filter(CbamData.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="CBAM数据不存在")

    old_values = {
        "product_category": item.product_category,
        "product_quantity": item.product_quantity,
        "eu_carbon_price": item.eu_carbon_price,
        "eu_price_date": item.eu_price_date,
        "footprint_scope": item.footprint_scope,
        "status": item.status,
        "notes": item.notes,
    }

    if payload.product_category is not None:
        item.product_category = payload.product_category
    if payload.product_quantity is not None:
        item.product_quantity = payload.product_quantity
    if payload.eu_carbon_price is not None:
        item.eu_carbon_price = payload.eu_carbon_price
    if payload.eu_price_date is not None:
        item.eu_price_date = payload.eu_price_date
    if payload.footprint_scope is not None:
        item.footprint_scope = payload.footprint_scope
    if payload.status is not None:
        item.status = payload.status
    if payload.notes is not None:
        item.notes = payload.notes

    item.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(item)

    log_cbam_audit(
        db,
        project_id=item.project_id,
        batch_id=item.batch_id,
        data_id=item_id,
        action_type="update_cbam_item",
        action_description=f"更新 CBAM 数据: {item.product_name}",
        old_value=old_values,
        new_value=payload.model_dump(exclude_none=True),
        created_by=current_user.id,
    )

    from app.models.user import User

    creator = db.query(User).filter(User.id == item.created_by).first()
    return {
        "id": item.id,
        "product_name": item.product_name,
        "product_category": item.product_category,
        "product_quantity": item.product_quantity,
        "unit": item.unit,
        "carbon_footprint": item.carbon_footprint,
        "footprint_scope": item.footprint_scope,
        "eu_carbon_price": item.eu_carbon_price,
        "eu_price_date": item.eu_price_date,
        "carbon_tariff": item.carbon_tariff,
        "currency": item.currency,
        "status": item.status,
        "notes": item.notes,
        "created_at": item.created_at,
        "created_by_username": creator.username if creator else None,
    }


@router.get("/items/{project_id}", response_model=CbamListResponse)
def list_cbam_items(
    project_id: int,
    batch_id: int | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> CbamListResponse:
    ensure_project_exists(db, project_id)
    
    query = db.query(CbamData).filter(CbamData.project_id == project_id)
    if batch_id:
        query = query.filter(CbamData.batch_id == batch_id)
    if status:
        query = query.filter(CbamData.status == status)
    
    items = query.order_by(CbamData.created_at.desc()).all()
    from app.models.user import User

    result = []
    total = len(items)
    for item in items:
        creator = db.query(User).filter(User.id == item.created_by).first()
        result.append({
            "id": item.id,
            "product_name": item.product_name,
            "product_category": item.product_category,
            "product_quantity": item.product_quantity,
            "unit": item.unit,
            "carbon_footprint": item.carbon_footprint,
            "footprint_scope": item.footprint_scope,
            "eu_carbon_price": item.eu_carbon_price,
            "eu_price_date": item.eu_price_date,
            "carbon_tariff": item.carbon_tariff,
            "currency": item.currency,
            "status": item.status,
            "notes": item.notes,
            "created_at": item.created_at,
            "created_by": item.created_by,
            "created_by_username": creator.username if creator else None,
        })

    return CbamListResponse(items=result, total=total)


@router.post("/batches/{project_id}", response_model=CbamBatchResponse)
def create_batch(
    project_id: int,
    payload: CbamBatchCreateRequest,
    db: Session = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> CbamBatchResponse:
    ensure_project_exists(db, project_id)
    
    errors = validate_cbam_parameters(payload.model_dump())
    if errors:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="; ".join(errors))

    batch_number = auto_assign_batch_number(project_id, db)
    
    batch = create_declaration_batch(
        db,
        project_id=project_id,
        batch_name=payload.batch_name,
        declaration_period_start=payload.declaration_period_start,
        declaration_period_end=payload.declaration_period_end,
        created_by=current_user.id,
    )

    return {
        "id": batch.id,
        "project_id": batch.project_id,
        "batch_name": batch.batch_name,
        "batch_number": batch.batch_number,
        "declaration_period_start": batch.declaration_period_start,
        "declaration_period_end": batch.declaration_period_end,
        "total_products": batch.total_products,
        "total_quantity": batch.total_quantity,
        "total_tariff": batch.total_tariff,
        "status": batch.status,
        "submitted_at": batch.submitted_at,
        "reviewed_at": batch.reviewed_at,
        "reviewed_by": batch.reviewed_by,
        "review_comment": batch.review_comment,
        "created_at": batch.created_at,
        "created_by": batch.created_by,
        "updated_at": batch.updated_at,
    }


@router.get("/batches/{project_id}", response_model=CbamBatchListResponse)
def list_batches(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> CbamBatchListResponse:
    ensure_project_exists(db, project_id)
    batches = get_project_cbam_batches(db, project_id)
    return CbamBatchListResponse(batches=batches, total=len(batches))


@router.post("/template/{project_id}", response_model=CbamTemplateResponse)
def export_cbam_template(
    project_id: int,
    batch_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> CbamTemplateResponse:
    ensure_project_exists(db, project_id)

    query = db.query(CbamData).filter(CbamData.project_id == project_id)
    if batch_id:
        query = query.filter(CbamData.batch_id == batch_id)
    
    items = query.all()
    if not items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请先提取 CBAM 数据后再导出模板",
        )

    file_name = build_template_filename(project_id)
    target_path = Path(settings.report_dir) / file_name
    file_path = generate_cbam_template(target_path, items)
    
    log_cbam_audit(
        db,
        project_id=project_id,
        batch_id=batch_id,
        action_type="export_template",
        action_description=f"导出 CBAM 模板，批次ID: {batch_id}",
        old_value=None,
        new_value={"item_count": len(items), "file_path": file_path},
        created_by=current_user.id,
    )

    return CbamTemplateResponse(file_path=file_path, batch_id=batch_id)


@router.get("/summary/{project_id}", response_model=CbamSummaryResponse)
def cbam_summary(
    project_id: int,
    batch_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> CbamSummaryResponse:
    ensure_project_exists(db, project_id)
    
    query = db.query(CbamData).filter(CbamData.project_id == project_id)
    if batch_id:
        query = query.filter(CbamData.batch_id == batch_id)
    
    items = query.all()
    summary = summarize_cbam(items)
    
    result_items = []
    for item in summary["items"]:
        result_items.append({
            "product_name": item["product_name"],
            "product_category": item["product_category"],
            "product_quantity": item["product_quantity"],
            "unit": item["unit"],
            "carbon_footprint": item["carbon_footprint"],
            "eu_carbon_price": item["eu_carbon_price"],
            "carbon_tariff": item["carbon_tariff"],
        })

    return CbamSummaryResponse(
        project_id=project_id,
        batch_id=batch_id,
        total_products=summary["total_products"],
        total_quantity=summary["total_quantity"],
        total_carbon_tariff=summary["total_carbon_tariff"],
        items=result_items,
    )


@router.post("/export-package/{project_id}", response_model=CbamExportPackageResponse)
def export_cbam_package(
    project_id: int,
    batch_id: int,
    db: Session = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> CbamExportPackageResponse:
    ensure_project_exists(db, project_id)
    items = db.query(CbamData).filter(CbamData.project_id == project_id, CbamData.batch_id == batch_id).all()
    if not items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请先录入 CBAM 数据后再导出材料包",
        )

    batch = db.query(CbamDeclarationBatch).filter(CbamDeclarationBatch.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")
    
    package_path = generate_cbam_export_package(Path(settings.report_dir), project_id, batch_id)
    
    log_cbam_audit(
        db,
        project_id=project_id,
        batch_id=batch_id,
        action_type="export_package",
        action_description=f"导出 CBAM 申报材料包: {batch.batch_name}",
        old_value=None,
        new_value={"package_path": package_path, "item_count": len(items)},
        created_by=current_user.id,
    )

    return CbamExportPackageResponse(
        package_path=package_path,
        batch_id=batch_id,
        batch_name=batch.batch_name,
    )


@router.post("/review/{batch_id}", response_model=CbamReviewResponse)
def review_batch(
    batch_id: int,
    payload: CbamReviewRequest,
    db: Session = Depends(get_db),
    current_user: Any = Depends(require_admin),
) -> CbamReviewResponse:
    batch = db.query(CbamDeclarationBatch).filter(CbamDeclarationBatch.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")
    
    batch.status = payload.status
    batch.reviewed_by = current_user.id
    batch.reviewed_at = datetime.utcnow()
    batch.review_comment = payload.review_comment
    db.commit()
    
    log_cbam_audit(
        db,
        project_id=batch.project_id,
        batch_id=batch.id,
        action_type="review_batch",
        action_description=f"审核批次: {payload.status}",
        old_value={"old_status": batch.status},
        new_value={"new_status": payload.status, "review_comment": payload.review_comment},
        created_by=current_user.id,
    )

    return CbamReviewResponse(
        success=True,
        message=f"批次 {batch.batch_name} 已标记为 {payload.status}",
    )


@router.post("/evidences/{batch_id}", response_model=CbamEvidenceResponse)
def upload_evidence(
    batch_id: int,
    payload: CbamEvidenceUploadRequest,
    db: Session = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> CbamEvidenceResponse:
    batch = db.query(CbamDeclarationBatch).filter(CbamDeclarationBatch.id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")
    
    evidence = CbamEvidence(
        batch_id=batch_id,
        evidence_type=payload.evidence_type,
        evidence_name=payload.evidence_name,
        description=payload.description,
        file_size=0,
        uploaded_by=current_user.id,
    )
    db.add(evidence)
    db.commit()
    db.refresh(evidence)
    
    log_cbam_audit(
        db,
        project_id=batch.project_id,
        batch_id=batch_id,
        action_type="upload_evidence",
        action_description=f"上传证据材料: {payload.evidence_name}",
        old_value=None,
        new_value={"evidence_type": payload.evidence_type, "evidence_name": payload.evidence_name},
        created_by=current_user.id,
    )

    return {
        "id": evidence.id,
        "evidence_type": evidence.evidence_type,
        "evidence_name": evidence.evidence_name,
        "file_path": evidence.file_path,
        "file_size": evidence.file_size,
        "description": evidence.description,
        "uploaded_at": evidence.uploaded_at,
        "uploaded_by": evidence.uploaded_by,
    }


# ---------------------------------------------------------------------------
# EUA (European Union Allowance) carbon futures price — real-time scraper
# ---------------------------------------------------------------------------

@router.get("/eu-carbon-price", response_model=EUAMarketPriceResponse)
def get_eu_carbon_price(
    force: bool = False,
) -> EUAMarketPriceResponse:
    """Fetch the latest EUA carbon futures price (EUR/tonne).

    Three-tier fallback: investing.com scraper → stale cache → offline benchmark.
    Set force=true to bypass the in-memory cache.
    """
    logger.info("API /cbam/eu-carbon-price force=%s", force)
    snap, _trace = fetch_eua_price(force=force)
    return EUAMarketPriceResponse(**snap.to_dict())


@router.get("/test-eu-carbon-price", response_model=EUAMarketPriceDebugResponse)
def test_eu_carbon_price(
    force: bool = True,
) -> EUAMarketPriceDebugResponse:
    """Debug endpoint — returns full execution trace alongside the price snapshot."""
    logger.info("API /cbam/test-eu-carbon-price force=%s", force)
    snap, trace = fetch_eua_price(force=force)
    return EUAMarketPriceDebugResponse(
        source=snap.source,
        success=snap.price > 0,
        price=snap.price,
        price_date=snap.price_date,
        volume=snap.volume,
        turnover=snap.turnover,
        fallback_layer=snap.fallback_layer,
        settlement_date=snap.settlement_date,
        trace=trace,
        snapshot=EUAMarketPriceResponse(**snap.to_dict()),
    )
