from datetime import datetime
from pydantic import BaseModel, ConfigDict


class ReportResponse(BaseModel):
    report_id: int
    file_path: str


class ReportRecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    type: str
    file_path: str
    created_at: datetime

