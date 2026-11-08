from datetime import date, datetime
from sqlalchemy import Boolean, Date, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    organization: Mapped[str] = mapped_column(String(255), nullable=False)
    boundary: Mapped[str] = mapped_column(String(255), nullable=False)
    boundary_method: Mapped[str] = mapped_column(String(64), nullable=False)
    base_year: Mapped[int] = mapped_column(Integer, nullable=False)
    report_year: Mapped[int] = mapped_column(Integer, nullable=False)
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    standard: Mapped[str] = mapped_column(String(128), nullable=False)
    calculation_profile: Mapped[str] = mapped_column(String(32), nullable=False, default="AUTO")
    industry: Mapped[str] = mapped_column(String(128), nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    emission_sources = relationship(
        "EmissionSource",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    reports = relationship("ReportRecord", back_populates="project", cascade="all, delete-orphan")
    carbon_market_records = relationship(
        "CarbonMarketRecord",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    cbam_entries = relationship("CbamData", back_populates="project", cascade="all, delete-orphan")
    compliance_snapshots = relationship("ComplianceSnapshot", cascade="all, delete-orphan")
    market_price_configs = relationship("MarketPriceConfig", cascade="all, delete-orphan")
    compliance_param_versions = relationship("ComplianceParamVersion", cascade="all, delete-orphan")
    cbam_declaration_batches = relationship("CbamDeclarationBatch", cascade="all, delete-orphan")
    allowance_accounts = relationship("AllowanceAccount", cascade="all, delete-orphan")
    allowance_transactions = relationship("AllowanceTransaction", cascade="all, delete-orphan")
    natural_gas_timeseries = relationship("NaturalGasTimeseries", cascade="all, delete-orphan")
    purchased_electricity_timeseries = relationship("PurchasedElectricityTimeseries", cascade="all, delete-orphan")

