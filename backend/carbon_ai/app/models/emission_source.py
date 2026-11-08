from datetime import date, datetime
from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


ISO_CATEGORY_NAME_MAP = {
    "1.1": "固定燃烧",
    "1.2": "工艺排放",
    "1.3": "移动燃烧",
    "1.4": "无组织排放",
    "1.5": "生物质燃烧",
    "2.1": "电力产生的间接温室气体排放",
    "2.2": "热力产生的间接温室气体排放",
    "3.1": "其他间接温室气体排放",
}


class EmissionSource(Base):
    __tablename__ = "emission_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    scope: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    activity_data: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(64), nullable=False)
    factor: Mapped[float] = mapped_column(Float, nullable=False)
    factor_source: Mapped[str] = mapped_column(String(255), nullable=False)
    gas: Mapped[str] = mapped_column(String(32), nullable=False, default="CO2")
    gwp: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    co2e: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    emission_class: Mapped[str] = mapped_column(String(16), nullable=False, default="direct")
    energy_type: Mapped[str] = mapped_column(String(16), nullable=False, default="fuel")
    consumption_type: Mapped[str] = mapped_column(String(16), nullable=False, default="purchased")
    ghg_category: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    is_green_electricity: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    iso_category_major: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    iso_category_code: Mapped[str] = mapped_column(String(16), nullable=False, default="1.1")
    is_removal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_storage: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    project = relationship("Project", back_populates="emission_sources")
    uncertainties = relationship("UncertaintyAssessment", back_populates="source", cascade="all, delete-orphan")
    evidences = relationship("EvidenceRecord", back_populates="source", cascade="all, delete-orphan")

    @property
    def iso_category_name(self) -> str:
        code = (self.iso_category_code or "").strip()
        if code in ISO_CATEGORY_NAME_MAP:
            return ISO_CATEGORY_NAME_MAP[code]
        if self.iso_category_major == 1:
            return "固定燃烧"
        if self.iso_category_major == 2:
            return "电力产生的间接温室气体排放"
        return "其他间接温室气体排放"
