from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.cbam_data import CbamData
from app.models.cbam_declaration_batch import CbamDeclarationBatch
from app.services.agent.types import AgentTool


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _execute_list_batches(db: Session, arguments: dict[str, Any]) -> dict[str, Any]:
    project_id = _safe_int(arguments.get("project_id"), 0)
    if project_id <= 0:
        return {"error": "missing project_id"}
    rows = (
        db.query(CbamDeclarationBatch)
        .filter(CbamDeclarationBatch.project_id == project_id)
        .order_by(CbamDeclarationBatch.created_at.desc())
        .all()
    )
    return {
        "project_id": project_id,
        "total": len(rows),
        "batches": [
            {
                "id": r.id,
                "batch_name": r.batch_name,
                "batch_number": r.batch_number,
                "status": r.status,
                "total_products": r.total_products,
                "total_quantity": r.total_quantity,
                "total_tariff": r.total_tariff,
            }
            for r in rows
        ],
    }


def _execute_batch_summary(db: Session, arguments: dict[str, Any]) -> dict[str, Any]:
    batch_id = _safe_int(arguments.get("batch_id"), 0)
    if batch_id <= 0:
        return {"error": "missing batch_id"}
    batch = db.query(CbamDeclarationBatch).filter(CbamDeclarationBatch.id == batch_id).first()
    if not batch:
        return {"error": f"batch_not_found: {batch_id}"}
    items = db.query(CbamData).filter(CbamData.batch_id == batch_id).all()
    total_tariff = float(sum(float(i.carbon_tariff or 0.0) for i in items))
    return {
        "batch_id": batch_id,
        "batch_name": batch.batch_name,
        "status": batch.status,
        "total_products": len(items),
        "total_tariff": total_tariff,
    }


def _execute_compliance_risk(db: Session, arguments: dict[str, Any]) -> dict[str, Any]:
    batch_id = _safe_int(arguments.get("batch_id"), 0)
    if batch_id <= 0:
        return {"error": "missing batch_id"}
    batch = db.query(CbamDeclarationBatch).filter(CbamDeclarationBatch.id == batch_id).first()
    if not batch:
        return {"error": f"batch_not_found: {batch_id}"}
    items = db.query(CbamData).filter(CbamData.batch_id == batch_id).all()
    if not items:
        return {"error": f"batch_empty: {batch_id}"}

    risks: list[dict[str, str]] = []
    if float(sum(float(i.carbon_tariff or 0.0) for i in items)) > 500000:
        risks.append({"level": "high", "type": "tariff", "description": "High total CBAM tariff"})
    if any((i.product_category or "").strip() == "" for i in items):
        risks.append({"level": "medium", "type": "category", "description": "Uncategorized products exist"})
    if batch.status in {"needs_revision", "rejected"}:
        risks.append({"level": "high", "type": "review", "description": "Batch review is not approved"})

    level = "low"
    if any(r["level"] == "high" for r in risks):
        level = "high"
    elif any(r["level"] == "medium" for r in risks):
        level = "medium"

    return {"batch_id": batch_id, "risk_level": level, "risks": risks}


def build_cbam_batches_tool() -> AgentTool:
    return AgentTool(
        name="get_cbam_batches",
        description="List CBAM declaration batches for a project.",
        parameters={"project_id": {"type": "integer", "description": "Project ID"}},
        execute=_execute_list_batches,
    )


def build_cbam_batch_summary_tool() -> AgentTool:
    return AgentTool(
        name="get_cbam_batch_summary",
        description="Get summary of a CBAM batch.",
        parameters={"batch_id": {"type": "integer", "description": "Batch ID"}},
        execute=_execute_batch_summary,
    )


def build_cbam_risk_tool() -> AgentTool:
    return AgentTool(
        name="get_cbam_compliance_risk",
        description="Evaluate compliance risks for CBAM batch.",
        parameters={"batch_id": {"type": "integer", "description": "Batch ID"}},
        execute=_execute_compliance_risk,
    )
