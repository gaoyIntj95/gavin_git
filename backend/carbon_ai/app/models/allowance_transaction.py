from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class AllowanceTransaction(Base):
    __tablename__ = "allowance_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("allowance_accounts.id", ondelete="SET NULL"), nullable=True)
    txn_type: Mapped[str] = mapped_column(String(32), nullable=False)  # buy/sell/offset/allocate
    instrument: Mapped[str] = mapped_column(String(32), nullable=False)  # quota/ccer/green_power
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, nullable=False)
    total_amount: Mapped[float] = mapped_column(Float, nullable=False)
    txn_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    reference_no: Mapped[str | None] = mapped_column(String(128), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    project = relationship("Project", overlaps="allowance_transactions")
    account = relationship("AllowanceAccount")
    creator = relationship("User")
