from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy.orm import Session

ToolExecutor = Callable[[Session, dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class AgentTool:
    name: str
    description: str
    parameters: dict[str, Any]
    execute: ToolExecutor

