from datetime import date
from sqlalchemy import Date, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class FactorLibrary(Base):
    __tablename__ = "factor_library"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(128), nullable=False)
    industry: Mapped[str | None] = mapped_column(String(128), nullable=True)
    region: Mapped[str | None] = mapped_column(String(128), nullable=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(255), nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    emission_class: Mapped[str] = mapped_column(String(16), nullable=False, default="direct")
    energy_type: Mapped[str] = mapped_column(String(16), nullable=False, default="fuel")
    consumption_type: Mapped[str] = mapped_column(String(16), nullable=False, default="purchased")
    gas: Mapped[str] = mapped_column(String(32), nullable=False, default="CO2")
    standard_code: Mapped[str] = mapped_column(String(64), nullable=False, default="JS/T 303-2026")
