from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.services.agent.types import AgentTool
from app.services.nl2sql_service import query_by_nl2sql


def _execute(db: Session, arguments: dict[str, Any]) -> dict[str, Any]:
    question = str(arguments.get("question", "")).strip()
    if not question:
        return {"error": "缺少 question 参数"}
    project_id = arguments.get("project_id")
    limit = arguments.get("limit", 50)
    try:
        limit = int(limit)
    except Exception:
        limit = 50
    return query_by_nl2sql(
        db=db,
        question=question,
        project_id=int(project_id) if project_id is not None else None,
        limit=limit,
    )


def build_nl2sql_tool() -> AgentTool:
    return AgentTool(
        name="query_by_nl2sql",
        description="将自然语言问题转换为只读 SQL 后查询数据库（仅 SELECT，受安全白名单限制）",
        parameters={
            "question": {"type": "string", "description": "自然语言问题"},
            "project_id": {"type": "integer", "description": "可选项目ID"},
            "limit": {"type": "integer", "description": "可选返回行数上限"},
        },
        execute=_execute,
    )

