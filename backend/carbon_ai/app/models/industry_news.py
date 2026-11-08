from datetime import datetime
from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class IndustryNews(Base):
    __tablename__ = "industry_news"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_name: Mapped[str] = mapped_column(String(128), nullable=False)
    source_url: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    fingerprint: Mapped[str] = mapped_column(String(32), nullable=False, default="", index=True, unique=True)
    tags_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    kg_extract_version: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    kg_extracted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    kg_last_status: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    kg_last_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
