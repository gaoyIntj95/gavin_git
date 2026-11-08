from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class UncertaintyAssessment(Base):
    __tablename__ = "uncertainty_assessments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("emission_sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    emission_source_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    facility: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    activity_data_category: Mapped[str] = mapped_column(String(64), nullable=False, default="定期量测/抄表/铭牌")
    factor_category: Mapped[str] = mapped_column(String(64), nullable=False, default="国家排放因子")
    activity_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    factor_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    average_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    emission_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    emission_share: Mapped[float | None] = mapped_column(Float, nullable=True)
    weighted_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    source = relationship("EmissionSource", back_populates="uncertainties")
