from datetime import datetime

from sqlalchemy import JSON, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, new_id, utcnow


class Baseline(Base):
    """A per-speed (档) calibration baseline and its validity/fencing state."""

    __tablename__ = "baselines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tier: Mapped[str] = mapped_column(String(8), index=True)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    generation: Mapped[int] = mapped_column(Integer, default=1)
    fence: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"), nullable=True, index=True)
    dataset_id: Mapped[str | None] = mapped_column(ForeignKey("datasets.id"), nullable=True, index=True)
    source_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)

    parameter: Mapped[float | None] = mapped_column(Float, nullable=True)
    threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    fit_reels: Mapped[list] = mapped_column(JSON, default=list)
    holdout_reels: Mapped[list] = mapped_column(JSON, default=list)
    used_reels: Mapped[list] = mapped_column(JSON, default=list)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    actor: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
