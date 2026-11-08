from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ComplianceParamVersion(Base):
    __tablename__ = "compliance_param_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    version_name: Mapped[str] = mapped_column(String(128), nullable=False)
    allocation_method: Mapped[str] = mapped_column(String(64), nullable=False)
    carbon_price: Mapped[float] = mapped_column(Float, nullable=False)
    ccer_price: Mapped[float] = mapped_column(Float, nullable=False)
    green_electricity_price: Mapped[float] = mapped_column(Float, nullable=False)
    ccer_max_ratio: Mapped[float] = mapped_column(Float, nullable=False)
    green_power_max_ratio: Mapped[float] = mapped_column(Float, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    project = relationship("Project", overlaps="compliance_param_versions")
    creator = relationship("User")
