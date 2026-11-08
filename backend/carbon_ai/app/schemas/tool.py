from __future__ import annotations

from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    arguments: dict[str, Any] = Field(..., description="Tool arguments")


class ToolDefinition(BaseModel):
    name: str
    display_name: str
    description: str
    parameters: list[dict[str, Any]]
    category: str = "general"
