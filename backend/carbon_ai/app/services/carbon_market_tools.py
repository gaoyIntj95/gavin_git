from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.compliance_snapshot import ComplianceSnapshot
from app.models.carbon_market import CarbonMarketRecord
from app.models.compliance_audit_log import ComplianceAuditLog
from app.schemas.tool import ToolDefinition

logger = logging.getLogger(__name__)

AVAILABLE_TOOLS: list[ToolDefinition] = []


def get_tool(name: str) -> ToolDefinition | None:
    for tool in AVAILABLE_TOOLS:
        if tool.name == name:
            return tool
    return None


def list_tools(category: str | None = None) -> list[ToolDefinition]:
    if category:
        return [t for t in AVAILABLE_TOOLS if t.category == category]
    return AVAILABLE_TOOLS


def register_tool(tool: ToolDefinition) -> None:
    global AVAILABLE_TOOLS
    AVAILABLE_TOOLS.append(tool)


def get_compliance_analysis(db: Session, project_id: int) -> dict[str, Any]:
    """获取项目履约分析数据"""
    from app.models.user import User

    record = (
        db.query(CarbonMarketRecord, User)
        .join(User, CarbonMarketRecord.created_by == User.id, isouter=True)
        .filter(CarbonMarketRecord.project_id == project_id)
        .order_by(CarbonMarketRecord.created_at.desc())
        .first()
    )

    if not record:
        return {
            "error": f"项目 {project_id} 没有履约记录，请先进行履约测算",
            "project_id": project_id,
        }

    return {
        "project_id": project_id,
        "allocation_method": record.allocation_method,
        "carbon_price": record.carbon_price,
        "ccer_price": record.ccer_price,
        "green_electricity_price": record.green_electricity_price,
        "total_emission": record.total_emission,
        "free_quota": record.free_quota,
        "quota_gap": record.quota_gap,
        "optimal_cost": record.optimal_cost,
        "is_final": record.is_final,
        "created_at": record.created_at.isoformat(),
        "created_by_username": record.creator.username if record.creator else "系统",
    }


def get_compliance_snapshots(db: Session, project_id: int) -> list[dict[str, Any]]:
    """获取项目履约快照列表"""
    snapshots = (
        db.query(ComplianceSnapshot)
        .filter(ComplianceSnapshot.project_id == project_id)
        .order_by(ComplianceSnapshot.created_at.desc())
        .limit(10)
        .all()
    )

    return [
        {
            "id": s.id,
            "snapshot_name": s.snapshot_name,
            "allocation_method": s.allocation_method,
            "carbon_price": s.carbon_price,
            "recommended_plan": s.recommended_plan,
            "recommended_saving_ratio": s.recommended_saving_ratio,
            "is_final": s.is_final,
            "created_at": s.created_at.isoformat(),
        }
        for s in snapshots
    ]


def get_compliance_audit_trail(db: Session, project_id: int, limit: int = 20) -> list[dict[str, Any]]:
    """获取履约审计轨迹"""
    logs = (
        db.query(ComplianceAuditLog)
        .filter(ComplianceAuditLog.project_id == project_id)
        .order_by(ComplianceAuditLog.created_at.desc())
        .limit(limit)
        .all()
    )

    from app.models.user import User

    result = []
    for log in logs:
        creator = db.query(User).filter(User.id == log.created_by).first()
        result.append({
            "id": log.id,
            "action_type": log.action_type,
            "action_description": log.action_description,
            "old_value": json.loads(log.old_value) if log.old_value else None,
            "new_value": json.loads(log.new_value) if log.new_value else None,
            "changed_fields": log.changed_fields.split(",") if log.changed_fields else [],
            "created_at": log.created_at.isoformat(),
            "created_by_username": creator.username if creator else "系统",
        })

    return result


def get_compliance_recommendation(db: Session, project_id: int) -> dict[str, Any]:
    """获取履约优化建议"""
    analysis = get_compliance_analysis(db, project_id)
    if "error" in analysis:
        return analysis

    recommendations = []

    if analysis["optimal_cost"] > 0:
        full_quota_cost = analysis["quota_gap"] * analysis["carbon_price"]
        saving_ratio = (full_quota_cost - analysis["optimal_cost"]) / full_quota_cost if full_quota_cost > 0 else 0

        if saving_ratio > 0.10:
            recommendations.append({
                "type": "cost_optimization",
                "priority": "high",
                "title": "显著成本优化建议",
                "description": f"通过使用 CCER 和绿电抵扣，预计可节省 {saving_ratio:.1%} 的履约成本。",
                "details": {
                    "current_cost": analysis["optimal_cost"],
                    "full_quota_cost": full_quota_cost,
                    "saving": full_quota_cost - analysis["optimal_cost"],
                },
            })

    if analysis["is_final"]:
        recommendations.append({
            "type": "final_version",
            "priority": "info",
            "title": "已标记为最终版本",
            "description": "该履约方案已标记为最终版本，建议不再修改。",
        })

    if not analysis["is_final"]:
        recommendations.append({
            "type": "finalize_suggestion",
            "priority": "medium",
            "title": "建议标记为最终版本",
            "description": "履约方案已稳定，建议标记为最终版本以便归档。",
        })

    return {
        "project_id": project_id,
        "analysis": analysis,
        "recommendations": recommendations,
    }


register_tool(
    ToolDefinition(
        name="get_compliance_analysis",
        display_name="获取履约分析",
        description="获取指定项目的碳市场履约分析数据，包括配额缺口、最优方案、成本等",
        parameters=[
            {"name": "project_id", "type": "integer", "description": "项目ID"},
        ],
        category="carbon_market",
    )
)

register_tool(
    ToolDefinition(
        name="get_compliance_snapshots",
        display_name="获取履约快照",
        description="获取项目的履约方案快照列表，最多返回最近10个",
        parameters=[
            {"name": "project_id", "type": "integer", "description": "项目ID"},
        ],
        category="carbon_market",
    )
)

register_tool(
    ToolDefinition(
        name="get_compliance_audit_trail",
        display_name="获取履约审计轨迹",
        description="获取项目的履约操作审计日志，用于追溯决策过程",
        parameters=[
            {"name": "project_id", "type": "integer", "description": "项目ID"},
            {"name": "limit", "type": "integer", "description": "返回条数（可选，默认20）"},
        ],
        category="carbon_market",
    )
)

register_tool(
    ToolDefinition(
        name="get_compliance_recommendation",
        display_name="获取履约优化建议",
        description="基于当前履约数据提供智能优化建议和风险提示",
        parameters=[
            {"name": "project_id", "type": "integer", "description": "项目ID"},
        ],
        category="carbon_market",
    )
)
