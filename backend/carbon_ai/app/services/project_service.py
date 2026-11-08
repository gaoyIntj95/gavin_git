from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.project import Project


PROJECT_NOT_FOUND_DETAIL = "项目不存在"


def active_project_query(db: Session):
    return db.query(Project).filter(Project.is_deleted.is_(False))


def get_project_or_404(db: Session, project_id: int) -> Project:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail=PROJECT_NOT_FOUND_DETAIL)
    return project


def ensure_project_exists(db: Session, project_id: int) -> None:
    get_project_or_404(db, project_id)


def get_active_project_or_404(db: Session, project_id: int) -> Project:
    project = active_project_query(db).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail=PROJECT_NOT_FOUND_DETAIL)
    return project
