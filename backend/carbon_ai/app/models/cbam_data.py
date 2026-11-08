from datetime import datetime
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class CbamData(Base):
    __tablename__ = "cbam_data"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("cbam_declaration_batches.id", ondelete="SET NULL"), nullable=True)
    product_name: Mapped[str] = mapped_column(String(255), nullable=False)
    product_category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    product_quantity: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(64), nullable=False)
    carbon_footprint: Mapped[float] = mapped_column(Float, nullable=False)
    footprint_scope: Mapped[str | None] = mapped_column(String(64), nullable=True)
    eu_carbon_price: Mapped[float] = mapped_column(Float, nullable=False)
    eu_price_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    carbon_tariff: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(16), default="EUR")
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    project = relationship("Project")
    batch = relationship("CbamDeclarationBatch")
    creator = relationship("User")
