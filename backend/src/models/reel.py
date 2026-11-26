from datetime import datetime

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, utcnow


class RevokedReel(Base):
    """A qualified reel (合格卷) whose qualification has been revoked."""

    __tablename__ = "revoked_reels"

    reel: Mapped[str] = mapped_column(String(120), primary_key=True)
    tier: Mapped[str | None] = mapped_column(String(8), nullable=True, index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
