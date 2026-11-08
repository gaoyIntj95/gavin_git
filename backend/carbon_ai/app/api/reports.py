from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.report import ReportRecord
from app.schemas.report import ReportResponse
from app.services.project_service import ensure_project_exists
from app.services.report_service import (
    generate_cbam_report,
    generate_compliance_report,
    generate_inventory_report,
)


router = APIRouter(prefix="/reports", tags=["reports"])


def _save_report_record(db: Session, project_id: int, report_type: str, file_path: str) -> ReportRecord:
    record = ReportRecord(project_id=project_id, type=report_type, file_path=file_path)
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.post("/inventory/{project_id}", response_model=ReportResponse)
def create_inventory_report(project_id: int, db: Session = Depends(get_db)) -> ReportResponse:
    ensure_project_exists(db, project_id)
    file_path = generate_inventory_report(db, project_id)
    record = _save_report_record(db, project_id, "盘查报告", file_path)
    return ReportResponse(report_id=record.id, file_path=file_path)


@router.post("/compliance/{project_id}", response_model=ReportResponse)
def create_compliance_report(project_id: int, db: Session = Depends(get_db)) -> ReportResponse:
    ensure_project_exists(db, project_id)
    file_path = generate_compliance_report(db, project_id)
    record = _save_report_record(db, project_id, "履约报告", file_path)
    return ReportResponse(report_id=record.id, file_path=file_path)


@router.post("/cbam/{project_id}", response_model=ReportResponse)
def create_cbam_report(project_id: int, db: Session = Depends(get_db)) -> ReportResponse:
    ensure_project_exists(db, project_id)
    file_path = generate_cbam_report(db, project_id)
    record = _save_report_record(db, project_id, "CBAM 报告", file_path)
    return ReportResponse(report_id=record.id, file_path=file_path)


@router.get("/{report_id}/download")
def download_report(report_id: int, db: Session = Depends(get_db)) -> FileResponse:
    record = db.query(ReportRecord).filter(ReportRecord.id == report_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="报告不存在")
    file_path = Path(record.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="报告文件不存在")
    return FileResponse(path=file_path, filename=file_path.name)
