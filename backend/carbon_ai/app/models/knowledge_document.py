from datetime import datetime
from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    file_type: Mapped[str] = mapped_column(String(16), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    object_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    file_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    storage_provider: Mapped[str] = mapped_column(String(32), nullable=False, default="minio")
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="processing")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
