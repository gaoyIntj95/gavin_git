from datetime import datetime
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ComplianceSnapshot(Base):
    __tablename__ = "compliance_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    snapshot_name: Mapped[str] = mapped_column(String(255), nullable=False)
    allocation_method: Mapped[str] = mapped_column(String(64), nullable=False)
    carbon_price: Mapped[float] = mapped_column(Float, nullable=False)
    ccer_price: Mapped[float] = mapped_column(Float, nullable=False)
    green_electricity_price: Mapped[float] = mapped_column(Float, nullable=False)
    ccer_max_ratio: Mapped[float] = mapped_column(Float, nullable=False)
    green_power_max_ratio: Mapped[float] = mapped_column(Float, nullable=False)
    total_emission: Mapped[float] = mapped_column(Float, nullable=False)
    free_quota: Mapped[float] = mapped_column(Float, nullable=False)
    quota_gap: Mapped[float] = mapped_column(Float, nullable=False)
    plan_a_cost: Mapped[float] = mapped_column(Float, nullable=False)
    plan_b_cost: Mapped[float] = mapped_column(Float, nullable=False)
    plan_c_cost: Mapped[float] = mapped_column(Float, nullable=False)
    recommended_plan: Mapped[str] = mapped_column(String(64), nullable=False)
    recommended_saving_ratio: Mapped[float] = mapped_column(Float, nullable=False)
    snapshot_data: Mapped[str] = mapped_column(Text, nullable=True)
    is_final: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)

    project = relationship("Project", overlaps="compliance_snapshots")
    creator = relationship("User")
