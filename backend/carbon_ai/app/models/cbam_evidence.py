from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class CbamEvidence(Base):
    __tablename__ = "cbam_evidences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("cbam_declaration_batches.id", ondelete="CASCADE"), nullable=False)
    emission_source_id: Mapped[int | None] = mapped_column(ForeignKey("emission_sources.id", ondelete="SET NULL"), nullable=True)
    evidence_type: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(512), nullable=True)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)

    batch = relationship("CbamDeclarationBatch")
    emission_source = relationship("EmissionSource")
    uploader = relationship("User")
