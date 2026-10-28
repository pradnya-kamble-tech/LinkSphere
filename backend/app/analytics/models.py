from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, DateTime, BigInteger, ForeignKey, Identity, Index, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.db import Base


class ClickEvent(Base):
    __tablename__ = "click_events"

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=True), primary_key=True
    )
    link_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("links.id", ondelete="CASCADE"), nullable=False
    )
    clicked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    referrer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    device_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)

    link = relationship("Link", back_populates="click_events")

    __table_args__ = (
        Index("ix_click_events_link_id_clicked_at", "link_id", clicked_at.desc()),
    )
