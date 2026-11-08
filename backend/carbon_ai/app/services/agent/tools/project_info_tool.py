from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.project import Project
from app.services.agent.types import AgentTool


def get_project_info(db: Session, project_id: int) -> dict[str, Any]:
    project = db.query(Project).filter(Project.id == project_id, Project.is_deleted == False).first()
    if not project:
        return {"error": f"项目 ID={project_id} 不存在"}
    return {
        "id": project.id,
        "name": project.name,
        "organization": project.organization,
        "industry": project.industry,
        "standard": project.standard,
        "boundary": project.boundary,
        "boundary_method": project.boundary_method,
        "base_year": project.base_year,
        "report_year": project.report_year,
        "calculation_profile": project.calculation_profile,
    }


def _execute(db: Session, arguments: dict[str, Any]) -> dict[str, Any]:
    project_id = arguments.get("project_id")
    if project_id is None:
        return {"error": "缺少 project_id 参数"}
    return get_project_info(db, int(project_id))


def build_project_info_tool() -> AgentTool:
    return AgentTool(
        name="get_project_info",
        description="获取指定项目的基本信息，包括名称、组织、行业、核算标准、组织边界、边界方法、基准年、报告年等",
        parameters={"project_id": {"type": "integer", "description": "项目ID"}},
        execute=_execute,
    )

