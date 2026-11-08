from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.services.agent.types import AgentTool


class AgentToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, AgentTool] = {}

    def register(self, tool: AgentTool) -> None:
        self._tools[tool.name] = tool

    def get(self, tool_name: str) -> AgentTool | None:
        return self._tools.get(tool_name)

    def list_tools(self) -> list[AgentTool]:
        return list(self._tools.values())

    def dispatch(self, db: Session, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        tool = self.get(tool_name)
        if tool is None:
            return {"error": f"未知工具: {tool_name}"}
        return tool.execute(db, arguments)

