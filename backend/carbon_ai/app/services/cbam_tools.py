from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.cbam_data import CbamData
from app.models.cbam_declaration_batch import CbamDeclarationBatch


def get_cbam_batches(db: Session, project_id: int) -> dict[str, Any]:
    batches = (
        db.query(CbamDeclarationBatch)
        .filter(CbamDeclarationBatch.project_id == project_id)
        .order_by(CbamDeclarationBatch.created_at.desc())
        .all()
    )
    return {
        "project_id": project_id,
        "total_batches": len(batches),
        "batches": [
            {
                "id": b.id,
                "batch_name": b.batch_name,
                "batch_number": b.batch_number,
                "status": b.status,
                "total_products": b.total_products,
                "total_quantity": float(b.total_quantity),
                "total_tariff": float(b.total_tariff),
                "declaration_period_start": b.declaration_period_start.isoformat(),
                "declaration_period_end": b.declaration_period_end.isoformat(),
            }
            for b in batches
        ],
    }


def get_cbam_batch_summary(db: Session, batch_id: int) -> dict[str, Any]:
    batch = db.query(CbamDeclarationBatch).filter(CbamDeclarationBatch.id == batch_id).first()
    if not batch:
        return {"error": f"batch_not_found: {batch_id}"}
    items = db.query(CbamData).filter(CbamData.batch_id == batch_id).all()
    categories: dict[str, dict[str, float | int]] = {}
    for i in items:
        cat = i.product_category or "未分类"
        if cat not in categories:
            categories[cat] = {"count": 0, "quantity": 0.0, "tariff": 0.0}
        categories[cat]["count"] = int(categories[cat]["count"]) + 1
        categories[cat]["quantity"] = float(categories[cat]["quantity"]) + float(i.product_quantity or 0.0)
        categories[cat]["tariff"] = float(categories[cat]["tariff"]) + float(i.carbon_tariff or 0.0)
    return {
        "batch_id": batch_id,
        "project_id": batch.project_id,
        "batch_name": batch.batch_name,
        "batch_number": batch.batch_number,
        "status": batch.status,
        "total_products": len(items),
        "total_quantity": float(sum(float(i.product_quantity or 0.0) for i in items)),
        "total_tariff": float(sum(float(i.carbon_tariff or 0.0) for i in items)),
        "categories": categories,
    }


def get_cbam_compliance_risk(db: Session, batch_id: int) -> dict[str, Any]:
    batch = db.query(CbamDeclarationBatch).filter(CbamDeclarationBatch.id == batch_id).first()
    if not batch:
        return {"error": f"batch_not_found: {batch_id}"}
    items = db.query(CbamData).filter(CbamData.batch_id == batch_id).all()
    if not items:
        return {"error": f"batch_empty: {batch_id}"}

    risks: list[dict[str, str]] = []
    if float(batch.total_tariff or 0.0) > 500000:
        risks.append({"level": "high", "type": "tariff", "description": "碳关税总额较高"})
    if any((i.product_category or "").strip() == "" for i in items):
        risks.append({"level": "medium", "type": "category", "description": "存在未分类产品"})
    if batch.status in {"needs_revision", "rejected"}:
        risks.append({"level": "high", "type": "review", "description": "批次审核未通过"})

    level = "low"
    if any(r["level"] == "high" for r in risks):
        level = "high"
    elif any(r["level"] == "medium" for r in risks):
        level = "medium"

    return {
        "batch_id": batch_id,
        "batch_name": batch.batch_name,
        "risk_level": level,
        "risks": risks,
    }
