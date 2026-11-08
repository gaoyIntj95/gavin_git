from datetime import datetime
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class CbamDeclarationBatch(Base):
    __tablename__ = "cbam_declaration_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    batch_name: Mapped[str] = mapped_column(String(255), nullable=False)
    batch_number: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    declaration_period_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    declaration_period_end: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    total_products: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_quantity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    total_tariff: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    review_comment: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    project = relationship("Project", overlaps="cbam_declaration_batches")
    creator = relationship("User", foreign_keys=[created_by])
    reviewer = relationship("User", foreign_keys=[reviewed_by])
