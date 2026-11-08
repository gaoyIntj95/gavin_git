from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class NaturalGasTimeseries(Base):
    __tablename__ = "natural_gas_timeseries"
    __table_args__ = (
        UniqueConstraint("project_id", "period_type", "period_start", name="uk_ng_ts_project_period"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)

    # day / month / year
    period_type: Mapped[str] = mapped_column(String(16), nullable=False, default="month")
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)

    # Activity data for natural gas consumption
    activity_data: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    activity_unit: Mapped[str] = mapped_column(String(32), nullable=False, default="Nm3")

    # Emission factor and conversion settings
    factor: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    factor_unit: Mapped[str] = mapped_column(String(64), nullable=False, default="kgCO2e/Nm3")
    factor_source: Mapped[str] = mapped_column(String(255), nullable=False, default="JS/T 303-2026")
    gwp: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    gas: Mapped[str] = mapped_column(String(32), nullable=False, default="CO2")

    # Calculated emissions
    co2e: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    scope: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    iso_category_code: Mapped[str] = mapped_column(String(16), nullable=False, default="1.1")

    # Governance fields
    data_quality: Mapped[str] = mapped_column(String(16), nullable=False, default="measured")
    source_system: Mapped[str | None] = mapped_column(String(64), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    project = relationship("Project", back_populates="natural_gas_timeseries")

