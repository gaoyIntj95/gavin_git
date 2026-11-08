from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.services.agent.types import AgentTool
from app.services.graph_service import query_knowledge_graph


def _execute(db: Session, arguments: dict[str, Any]) -> dict[str, Any]:
    _ = db  # graph query does not require relational DB session
    question = str(arguments.get("question", "")).strip()
    if not question:
        return {"error": "缺少 question 参数"}
    entity = str(arguments.get("entity", "")).strip() or None
    top_k = arguments.get("top_k", 8)
    try:
        top_k = int(top_k)
    except Exception:
        top_k = 8
    top_k = max(1, min(top_k, 20))
    return query_knowledge_graph(question=question, entity=entity, top_k=top_k)


def build_knowledge_graph_tool() -> AgentTool:
    return AgentTool(
        name="knowledge_graph_query",
        description="查询双碳知识图谱中的术语关系、政策层级和标准关联，用于术语释义与政策溯源。",
        parameters={
            "question": {"type": "string", "description": "用户问题原文"},
            "entity": {"type": "string", "description": "可选，指定实体名（如 CBAM / CCER / ISO 14064）"},
            "top_k": {"type": "integer", "description": "可选，返回关系条数上限，默认 8"},
        },
        execute=_execute,
    )
