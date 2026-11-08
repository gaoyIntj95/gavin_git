from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.compliance_snapshot import ComplianceSnapshot
from app.models.compliance_audit_log import ComplianceAuditLog
from app.services.carbon_market_service import (
    calculate_quota_gap,
    optimize_compliance_cost,
    simulate_compliance_plans,
)

logger = logging.getLogger(__name__)

ALLOCATION_METHODS = {
    "grandfathering": 0.85,
    "benchmark": 0.80,
    "hybrid": 0.75,
}


def create_compliance_snapshot(
    db: Session,
    project_id: int,
    snapshot_name: str,
    allocation_method: str,
    carbon_price: float,
    ccer_price: float,
    green_electricity_price: float,
    total_emission: float,
    ccer_max_ratio: float = 0.30,
    green_power_max_ratio: float = 0.20,
    created_by: int | None = None,
) -> ComplianceSnapshot:
    free_quota, quota_gap = calculate_quota_gap(total_emission, allocation_method)
    
    result = simulate_compliance_plans(
        total_emission=total_emission,
        allocation_method=allocation_method,
        carbon_price=carbon_price,
        ccer_price=ccer_price,
        green_electricity_price=green_electricity_price,
        ccer_max_ratio=ccer_max_ratio,
        green_power_max_ratio=green_power_max_ratio,
    )
    
    best_plan = min(result["plans"], key=lambda x: x["total_cost"])
    
    snapshot = ComplianceSnapshot(
        project_id=project_id,
        snapshot_name=snapshot_name,
        allocation_method=allocation_method,
        carbon_price=carbon_price,
        ccer_price=ccer_price,
        green_electricity_price=green_electricity_price,
        ccer_max_ratio=ccer_max_ratio,
        green_power_max_ratio=green_power_max_ratio,
        total_emission=total_emission,
        free_quota=free_quota,
        quota_gap=quota_gap,
        plan_a_cost=result["plans"][0]["total_cost"],
        plan_b_cost=result["plans"][1]["total_cost"],
        plan_c_cost=result["plans"][2]["total_cost"],
        recommended_plan=result["recommended_plan"],
        recommended_saving_ratio=result["recommended_saving_ratio"],
        snapshot_data=json.dumps(result, ensure_ascii=False),
        created_by=created_by,
    )
    
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    
    return snapshot


def log_compliance_audit(
    db: Session,
    project_id: int,
    snapshot_id: int | None,
    action_type: str,
    action_description: str,
    old_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
    changed_fields: list[str] | None = None,
    created_by: int | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> ComplianceAuditLog:
    log = ComplianceAuditLog(
        project_id=project_id,
        snapshot_id=snapshot_id,
        action_type=action_type,
        action_description=action_description,
        old_value=json.dumps(old_value, ensure_ascii=False) if old_value else None,
        new_value=json.dumps(new_value, ensure_ascii=False) if new_value else None,
        changed_fields=",".join(changed_fields) if changed_fields else None,
        ip_address=ip_address,
        user_agent=user_agent,
        created_by=created_by,
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


def get_project_compliance_history(
    db: Session,
    project_id: int,
    limit: int = 50,
) -> list[dict[str, Any]]:
    from app.models.carbon_market import CarbonMarketRecord
    from app.models.user import User

    records = (
        db.query(CarbonMarketRecord, User)
        .join(User, CarbonMarketRecord.created_by == User.id, isouter=True)
        .filter(CarbonMarketRecord.project_id == project_id)
        .order_by(CarbonMarketRecord.created_at.desc())
        .limit(limit)
        .all()
    )
    
    result = []
    for record, user in records:
        result.append({
            "id": record.id,
            "allocation_method": record.allocation_method,
            "carbon_price": record.carbon_price,
            "ccer_price": record.ccer_price,
            "green_electricity_price": record.green_electricity_price,
            "total_emission": record.total_emission,
            "quota_gap": record.quota_gap,
            "optimal_cost": record.optimal_cost,
            "is_final": record.is_final,
            "created_at": record.created_at,
            "created_by": record.created_by,
            "created_by_username": user.username if user else None,
        })
    
    return result


def validate_compliance_parameters(params: dict[str, Any]) -> list[str]:
    errors = []
    
    carbon_price = params.get("carbon_price", 0)
    if carbon_price < 50 or carbon_price > 150:
        errors.append("碳价格应在 50-150 元/吨范围内")
    
    ccer_price = params.get("ccer_price", 0)
    if ccer_price < 30 or ccer_price > 80:
        errors.append("CCER价格应在 30-80 元/吨范围内")
    
    green_price = params.get("green_electricity_price", 0)
    if green_price < 50 or green_price > 100:
        errors.append("绿电价格应在 50-100 元/吨范围内")
    
    ccer_ratio = params.get("ccer_max_ratio", 0)
    if ccer_ratio > 0.50:
        errors.append("CCER抵消比例不能超过 50%")
    
    green_ratio = params.get("green_power_max_ratio", 0)
    if green_ratio > 0.30:
        errors.append("绿电抵扣比例不能超过 30%")
    
    allocation_method = params.get("allocation_method", "")
    if allocation_method not in ALLOCATION_METHODS:
        errors.append(f"分配方法应为: {', '.join(ALLOCATION_METHODS.keys())}")
    
    return errors
