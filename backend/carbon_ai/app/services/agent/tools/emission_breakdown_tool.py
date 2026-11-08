from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.emission_source import EmissionSource
from app.models.project import Project
from app.services.agent.types import AgentTool
from app.services.agent.tools.emission_summary_tool import get_emission_summary


def get_emission_breakdown(
    db: Session,
    project_id: int,
    group_by: str = "source",
    top_n: int = 10,
) -> dict[str, Any]:
    project = db.query(Project).filter(Project.id == project_id, Project.is_deleted == False).first()
    if not project:
        return {"error": f"项目 ID={project_id} 不存在"}

    summary = get_emission_summary(db, project_id)
    if summary.get("error"):
        return summary

    rows = (
        db.query(EmissionSource)
        .filter(EmissionSource.project_id == project_id)
        .order_by(EmissionSource.co2e.desc(), EmissionSource.id.asc())
        .all()
    )
    total = float(summary.get("total_emission", 0) or 0)

    def _pct(v: float) -> float:
        return round((v / total * 100), 2) if total > 0 else 0.0

    group_by_norm = (group_by or "source").strip().lower()
    items: list[dict[str, Any]] = []

    if group_by_norm == "scope":
        bucket: dict[str, float] = {}
        for r in rows:
            key = f"Scope {r.scope}"
            bucket[key] = bucket.get(key, 0.0) + float(r.co2e or 0.0)
        items = [
            {"name": k, "co2e": round(v, 4), "pct": _pct(v)}
            for k, v in sorted(bucket.items(), key=lambda kv: kv[1], reverse=True)
        ]
    elif group_by_norm == "category":
        bucket = {}
        for r in rows:
            key = str(r.category or "未知分类")
            bucket[key] = bucket.get(key, 0.0) + float(r.co2e or 0.0)
        items = [
            {"name": k, "co2e": round(v, 4), "pct": _pct(v)}
            for k, v in sorted(bucket.items(), key=lambda kv: kv[1], reverse=True)
        ]
    else:
        for r in rows:
            v = float(r.co2e or 0.0)
            items.append(
                {
                    "name": r.name,
                    "scope": r.scope,
                    "category": r.category,
                    "co2e": round(v, 4),
                    "pct": _pct(v),
                }
            )
        items.sort(key=lambda x: x.get("co2e", 0), reverse=True)

    n = max(1, min(int(top_n or 10), 50))
    return {
        "project_id": project_id,
        "project_name": project.name,
        "group_by": group_by_norm,
        "total_emission": total,
        "items": items[:n],
    }


def format_emission_breakdown_answer(breakdown: dict[str, Any]) -> str:
    if not isinstance(breakdown, dict):
        return "未获取到排放源拆分结果。"
    if breakdown.get("error"):
        return f"排放拆分查询失败：{breakdown.get('error')}"

    items = breakdown.get("items", []) or []
    if not items:
        return "当前项目暂无可拆分的排放源数据。"

    project_name = breakdown.get("project_name", "当前项目")
    group_by = breakdown.get("group_by", "source")
    total = float(breakdown.get("total_emission", 0) or 0)

    header = f"{project_name} 的排放拆分结果（按{group_by}）如下："
    lines = [header]
    for i, item in enumerate(items, 1):
        if group_by == "source":
            lines.append(
                f"{i}. {item.get('name')}（Scope {item.get('scope', 'N/A')}，{item.get('category', 'N/A')}）："
                f"{item.get('co2e', 0)} 吨，占比 {item.get('pct', 0)}%"
            )
        else:
            lines.append(
                f"{i}. {item.get('name')}：{item.get('co2e', 0)} 吨，占比 {item.get('pct', 0)}%"
            )
    if total > 0:
        lines.append(f"项目总排放量：{round(total, 4)} 吨二氧化碳当量")
    lines.append("如需我继续做同比、趋势或重点排放源治理建议，我可以继续展开。")
    return "\n".join(lines)


def _execute(db: Session, arguments: dict[str, Any]) -> dict[str, Any]:
    project_id = arguments.get("project_id")
    if project_id is None:
        return {"error": "缺少 project_id 参数"}
    group_by = str(arguments.get("group_by", "source")).strip().lower()
    top_n = arguments.get("top_n", 10)
    try:
        top_n = int(top_n)
    except Exception:
        top_n = 10
    return get_emission_breakdown(
        db=db,
        project_id=int(project_id),
        group_by=group_by,
        top_n=top_n,
    )


def build_emission_breakdown_tool() -> AgentTool:
    return AgentTool(
        name="get_emission_breakdown",
        description="获取项目排放明细拆分，可按 source/scope/category 聚合并返回占比",
        parameters={
            "project_id": {"type": "integer", "description": "项目ID"},
            "group_by": {"type": "string", "description": "source|scope|category"},
            "top_n": {"type": "integer", "description": "返回条数，默认10，最大50"},
        },
        execute=_execute,
    )

