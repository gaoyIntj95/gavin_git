from datetime import datetime
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class CarbonMarketRecord(Base):
    __tablename__ = "carbon_market"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    total_emission: Mapped[float] = mapped_column(Float, nullable=False)
    free_quota: Mapped[float] = mapped_column(Float, nullable=False)
    quota_gap: Mapped[float] = mapped_column(Float, nullable=False)
    carbon_price: Mapped[float] = mapped_column(Float, nullable=False)
    ccer_price: Mapped[float] = mapped_column(Float, nullable=False)
    green_electricity_price: Mapped[float] = mapped_column(Float, nullable=False)
    optimal_cost: Mapped[float] = mapped_column(Float, nullable=False)

    allocation_method: Mapped[str] = mapped_column(String(64), nullable=False)
    ccer_max_ratio: Mapped[float] = mapped_column(Float, nullable=False)
    green_power_max_ratio: Mapped[float] = mapped_column(Float, nullable=False)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_final: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    final_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    project = relationship("Project", back_populates="carbon_market_records")
    creator = relationship("User", foreign_keys=[created_by])
    updater = relationship("User", foreign_keys=[updated_by])
    creator = relationship("User", foreign_keys=[created_by])
    updater = relationship("User", foreign_keys=[updated_by])
