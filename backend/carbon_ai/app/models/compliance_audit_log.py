from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ComplianceAuditLog(Base):
    __tablename__ = "compliance_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("compliance_snapshots.id", ondelete="SET NULL"), nullable=True)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    action_description: Mapped[str] = mapped_column(String(512), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_fields: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    project = relationship("Project")
    snapshot = relationship("ComplianceSnapshot")
    creator = relationship("User")
