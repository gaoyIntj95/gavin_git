from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.services.agent.types import AgentTool
from app.services.calculation_service import calculate_project_totals
from app.services.carbon_market_service import simulate_compliance_plans
from app.services.compliance_audit_service import get_project_compliance_history


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _execute_summary(db: Session, arguments: dict[str, Any]) -> dict[str, Any]:
    project_id = _safe_int(arguments.get("project_id"), 0)
    if project_id <= 0:
        return {"error": "missing project_id"}
    totals = calculate_project_totals(db, project_id)
    return {
        "project_id": project_id,
        "total_emission": totals.get("total_emission", 0.0),
        "scope1": totals.get("scope1_emission", 0.0),
        "scope2": totals.get("scope2_emission", 0.0),
        "scope3": totals.get("scope3_emission", 0.0),
    }


def _execute_simulate(db: Session, arguments: dict[str, Any]) -> dict[str, Any]:
    project_id = _safe_int(arguments.get("project_id"), 0)
    if project_id <= 0:
        return {"error": "missing project_id"}

    totals = calculate_project_totals(db, project_id)
    return simulate_compliance_plans(
        total_emission=float(totals.get("total_emission", 0.0)),
        allocation_method=str(arguments.get("allocation_method", "benchmark")),
        carbon_price=_safe_float(arguments.get("carbon_price"), 85.0),
        ccer_price=_safe_float(arguments.get("ccer_price"), 60.0),
        green_electricity_price=_safe_float(arguments.get("green_electricity_price"), 70.0),
        ccer_max_ratio=_safe_float(arguments.get("ccer_max_ratio"), 0.30),
        green_power_max_ratio=_safe_float(arguments.get("green_power_max_ratio"), 0.20),
    )


def _execute_history(db: Session, arguments: dict[str, Any]) -> dict[str, Any]:
    project_id = _safe_int(arguments.get("project_id"), 0)
    if project_id <= 0:
        return {"error": "missing project_id"}
    limit = max(1, min(_safe_int(arguments.get("limit"), 10), 100))
    rows = get_project_compliance_history(db, project_id=project_id, limit=limit)
    return {"project_id": project_id, "total": len(rows), "records": rows}


def build_compliance_summary_tool() -> AgentTool:
    return AgentTool(
        name="get_compliance_summary",
        description="Get project emission summary for compliance context.",
        parameters={"project_id": {"type": "integer", "description": "Project ID"}},
        execute=_execute_summary,
    )


def build_compliance_simulate_tool() -> AgentTool:
    return AgentTool(
        name="simulate_compliance_plan",
        description="Simulate A/B/C compliance plans with market parameters.",
        parameters={
            "project_id": {"type": "integer", "description": "Project ID"},
            "allocation_method": {"type": "string", "description": "benchmark|grandfathering|hybrid"},
            "carbon_price": {"type": "number", "description": "Carbon price"},
            "ccer_price": {"type": "number", "description": "CCER price"},
            "green_electricity_price": {"type": "number", "description": "Green power offset price"},
            "ccer_max_ratio": {"type": "number", "description": "CCER max ratio"},
            "green_power_max_ratio": {"type": "number", "description": "Green power max ratio"},
        },
        execute=_execute_simulate,
    )


def build_compliance_history_tool() -> AgentTool:
    return AgentTool(
        name="get_compliance_history",
        description="Fetch compliance simulation and decision history.",
        parameters={
            "project_id": {"type": "integer", "description": "Project ID"},
            "limit": {"type": "integer", "description": "Max records"},
        },
        execute=_execute_history,
    )
