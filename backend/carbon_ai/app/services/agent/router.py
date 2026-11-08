from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.services.agent.registry import AgentToolRegistry


def execute_tool_call(
    db: Session,
    registry: AgentToolRegistry,
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    return registry.dispatch(db, tool_name, arguments)

