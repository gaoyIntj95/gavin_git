from __future__ import annotations

import csv
import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models.cbam_audit_log import CbamAuditLog
from app.models.cbam_data import CbamData
from app.models.cbam_declaration_batch import CbamDeclarationBatch

logger = logging.getLogger(__name__)


def create_declaration_batch(
    db: Session,
    project_id: int,
    batch_name: str,
    declaration_period_start: datetime,
    declaration_period_end: datetime,
    created_by: int | None = None,
) -> CbamDeclarationBatch:
    batch = CbamDeclarationBatch(
        project_id=project_id,
        batch_name=batch_name,
        batch_number=auto_assign_batch_number(project_id, db),
        declaration_period_start=declaration_period_start,
        declaration_period_end=declaration_period_end,
        created_by=created_by,
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)
    return batch


def log_cbam_audit(
    db: Session,
    project_id: int,
    action_type: str,
    action_description: str,
    batch_id: int | None = None,
    data_id: int | None = None,
    old_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
    changed_fields: list[str] | None = None,
    created_by: int | None = None,
) -> None:
    log = CbamAuditLog(
        project_id=project_id,
        batch_id=batch_id,
        data_id=data_id,
        action_type=action_type,
        action_description=action_description,
        old_value=json.dumps(old_value, ensure_ascii=False) if old_value else None,
        new_value=json.dumps(new_value, ensure_ascii=False) if new_value else None,
        changed_fields=",".join(changed_fields) if changed_fields else None,
        created_by=created_by or 1,
    )
    db.add(log)
    db.commit()


def get_project_cbam_batches(db: Session, project_id: int) -> list[dict[str, Any]]:
    rows = (
        db.query(CbamDeclarationBatch)
        .filter(CbamDeclarationBatch.project_id == project_id)
        .order_by(CbamDeclarationBatch.created_at.desc())
        .all()
    )
    result: list[dict[str, Any]] = []
    for row in rows:
        result.append(
            {
                "id": row.id,
                "project_id": row.project_id,
                "batch_name": row.batch_name,
                "batch_number": row.batch_number,
                "declaration_period_start": row.declaration_period_start,
                "declaration_period_end": row.declaration_period_end,
                "total_products": row.total_products,
                "total_quantity": row.total_quantity,
                "total_tariff": row.total_tariff,
                "status": row.status,
                "submitted_at": row.submitted_at,
                "reviewed_at": row.reviewed_at,
                "reviewed_by": row.reviewed_by,
                "review_comment": row.review_comment,
                "created_at": row.created_at,
                "created_by": row.created_by,
                "updated_at": row.updated_at,
            }
        )
    return result


def get_batch_cbam_items(db: Session, batch_id: int) -> list[dict[str, Any]]:
    rows = (
        db.query(CbamData)
        .filter(CbamData.batch_id == batch_id)
        .order_by(CbamData.created_at.asc())
        .all()
    )
    result: list[dict[str, Any]] = []
    for row in rows:
        result.append(
            {
                "id": row.id,
                "product_name": row.product_name,
                "product_category": row.product_category,
                "product_quantity": row.product_quantity,
                "unit": row.unit,
                "carbon_footprint": row.carbon_footprint,
                "footprint_scope": row.footprint_scope,
                "eu_carbon_price": row.eu_carbon_price,
                "eu_price_date": row.eu_price_date,
                "carbon_tariff": row.carbon_tariff,
                "currency": row.currency,
                "status": row.status,
                "notes": row.notes,
                "created_at": row.created_at,
                "created_by": row.created_by,
            }
        )
    return result


def generate_cbam_export_package(base_dir: Path, project_id: int, batch_id: int) -> str:
    batch = db_batch = None
    # lazy query wrapper keeps function signature stable
    # real query done in helper closure below
    def _load_from_db(session: Session) -> tuple[CbamDeclarationBatch, list[CbamData]]:
        _batch = session.query(CbamDeclarationBatch).filter(CbamDeclarationBatch.id == batch_id).first()
        if not _batch:
            raise ValueError(f"batch_not_found: {batch_id}")
        _items = (
            session.query(CbamData)
            .filter(CbamData.project_id == project_id, CbamData.batch_id == batch_id)
            .order_by(CbamData.created_at.asc())
            .all()
        )
        if not _items:
            raise ValueError(f"batch_empty: {batch_id}")
        return _batch, _items

    # acquire a session from existing object references
    # caller already validated batch/items in api; keep this helper defensive
    from app.core.database import SessionLocal

    with SessionLocal() as s:
        batch, items = _load_from_db(s)

    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    work_dir = Path(base_dir) / f"cbam_package_{project_id}_{batch_id}_{stamp}"
    work_dir.mkdir(parents=True, exist_ok=True)

    csv_path = work_dir / f"cbam_items_{batch_id}.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "product_name",
            "product_category",
            "product_quantity",
            "unit",
            "carbon_footprint",
            "footprint_scope",
            "eu_carbon_price",
            "eu_price_date",
            "carbon_tariff",
            "currency",
        ])
        for item in items:
            w.writerow([
                item.product_name,
                item.product_category,
                item.product_quantity,
                item.unit,
                item.carbon_footprint,
                item.footprint_scope,
                item.eu_carbon_price,
                item.eu_price_date.isoformat() if item.eu_price_date else "",
                item.carbon_tariff,
                item.currency,
            ])

    summary = {
        "project_id": project_id,
        "batch_id": batch_id,
        "batch_name": batch.batch_name,
        "batch_number": batch.batch_number,
        "total_products": len(items),
        "total_quantity": float(sum(i.product_quantity for i in items)),
        "total_tariff": float(sum(i.carbon_tariff for i in items)),
    }
    (work_dir / "cbam_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (work_dir / "README.txt").write_text(
        "\n".join([
            "CBAM申报材料包",
            f"project_id={project_id}",
            f"batch_id={batch_id}",
            f"batch_name={batch.batch_name}",
            f"generated_at={datetime.utcnow().isoformat()}Z",
        ]),
        encoding="utf-8",
    )

    archive_base = str(Path(base_dir) / f"cbam_package_{project_id}_{batch_id}_{stamp}")
    return shutil.make_archive(archive_base, "zip", root_dir=work_dir)


def validate_cbam_parameters(params: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if "eu_carbon_price" in params:
        p = float(params.get("eu_carbon_price") or 0)
        if p <= 0 or p > 300:
            errors.append("eu_carbon_price out of range")
    if "product_quantity" in params:
        q = float(params.get("product_quantity") or 0)
        if q <= 0:
            errors.append("product_quantity must be > 0")
    start = params.get("declaration_period_start")
    end = params.get("declaration_period_end")
    if start and end and end <= start:
        errors.append("declaration_period_end must be later than declaration_period_start")
    name = str(params.get("batch_name") or "").strip()
    if "batch_name" in params and (not name or len(name) > 255):
        errors.append("invalid batch_name")
    return errors


def auto_assign_batch_number(project_id: int, db: Session) -> str:
    prefix = datetime.utcnow().strftime("%Y%m")
    latest = (
        db.query(CbamDeclarationBatch)
        .filter(
            CbamDeclarationBatch.project_id == project_id,
            CbamDeclarationBatch.batch_number.like(f"{prefix}%"),
        )
        .order_by(CbamDeclarationBatch.batch_number.desc())
        .first()
    )
    if latest and str(latest.batch_number).startswith(prefix):
        try:
            seq = int(str(latest.batch_number)[-2:]) + 1
        except Exception:
            seq = 1
    else:
        seq = 1
    return f"{prefix}{seq:02d}"
