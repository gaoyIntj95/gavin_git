from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models.emission_source import EmissionSource
from app.models.project import Project
from app.services.agent.types import AgentTool
from app.services.calculation_service import calculate_project_totals

logger = logging.getLogger(__name__)


def get_emission_summary(db: Session, project_id: int) -> dict[str, Any]:
    project = db.query(Project).filter(Project.id == project_id, Project.is_deleted == False).first()
    if not project:
        return {"error": f"项目 ID={project_id} 不存在"}

    try:
        totals = calculate_project_totals(db, project_id)
    except Exception as exc:
        logger.error("Calculate project totals failed: %s", exc)
        return {"error": f"核算项目排放数据失败: {exc}"}

    sources = db.query(EmissionSource).filter(EmissionSource.project_id == project_id).all()
    top_sources = sorted(sources, key=lambda s: s.co2e, reverse=True)[:5]

    total_emission = float(totals.get("total_emission", 0) or 0)
    scope1 = float(totals.get("scope1_emission", 0) or 0)
    scope2 = float(totals.get("scope2_emission", 0) or 0)
    scope3 = float(totals.get("scope3_emission", 0) or 0)

    scope1_pct = round(scope1 / total_emission * 100, 1) if total_emission > 0 else 0
    scope2_pct = round(scope2 / total_emission * 100, 1) if total_emission > 0 else 0
    scope3_pct = round(scope3 / total_emission * 100, 1) if total_emission > 0 else 0

    return {
        "project_name": project.name,
        "total_emission": total_emission,
        "direct_emission": float(totals.get("direct_emission", 0) or 0),
        "indirect_emission": float(totals.get("indirect_emission", 0) or 0),
        "scope1_emission": scope1,
        "scope2_emission": scope2,
        "scope3_emission": scope3,
        "scope1_pct": scope1_pct,
        "scope2_pct": scope2_pct,
        "scope3_pct": scope3_pct,
        "calculation_profile": totals.get("calculation_profile", ""),
        "top_sources": [
            {
                "name": s.name,
                "category": s.category,
                "co2e": round(float(s.co2e or 0), 4),
                "scope": s.scope,
            }
            for s in top_sources
        ],
        "source_count": len(sources),
    }


def format_emission_summary_answer(summary: dict[str, Any]) -> str:
    if not isinstance(summary, dict):
        return "未获取到有效的项目排放汇总数据。"
    if summary.get("error"):
        return f"项目排放数据查询失败：{summary.get('error')}"

    project_name = summary.get("project_name", "当前项目")
    total_emission = summary.get("total_emission", 0)
    scope1_emission = summary.get("scope1_emission", 0)
    scope2_emission = summary.get("scope2_emission", 0)
    scope3_emission = summary.get("scope3_emission", 0)
    scope1_pct = summary.get("scope1_pct", 0)
    scope2_pct = summary.get("scope2_pct", 0)
    scope3_pct = summary.get("scope3_pct", 0)
    top_sources = summary.get("top_sources", []) or []

    lines = [
        f"根据业务数据查询结果，{project_name} 的排放汇总如下：",
        f"- 总排放量：{total_emission} 吨二氧化碳当量",
        f"- Scope 1：{scope1_emission} 吨（占比 {scope1_pct}%）",
        f"- Scope 2：{scope2_emission} 吨（占比 {scope2_pct}%）",
        f"- Scope 3：{scope3_emission} 吨（占比 {scope3_pct}%）",
    ]
    if top_sources:
        first = top_sources[0]
        lines.append(
            f"- 重点排放源：{first.get('name', '未知')}（{first.get('co2e', 0)} 吨，Scope {first.get('scope', 'N/A')}）"
        )
    lines.append("如需我继续拆分到排放源明细或计算口径，我可以继续展开。")
    return "\n".join(lines)


def _execute(db: Session, arguments: dict[str, Any]) -> dict[str, Any]:
    project_id = arguments.get("project_id")
    if project_id is None:
        return {"error": "缺少 project_id 参数"}
    return get_emission_summary(db, int(project_id))


def build_emission_summary_tool() -> AgentTool:
    return AgentTool(
        name="get_emission_summary",
        description="获取项目排放汇总，包括总量、Scope1/2/3、占比和重点排放源",
        parameters={"project_id": {"type": "integer", "description": "项目ID"}},
        execute=_execute,
    )

