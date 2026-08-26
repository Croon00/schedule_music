from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.common import TimestampMixin


class EventCandidateModel(TimestampMixin, Base):
    __tablename__ = "event_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    artist_id: Mapped[int] = mapped_column(ForeignKey("artists.id", ondelete="SET NULL"), nullable=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("artist_sources.id", ondelete="SET NULL"), nullable=True)
    event_type: Mapped[str] = mapped_column(Text, default="live_event")
    event_format: Mapped[str] = mapped_column(Text, default="unknown")
    title: Mapped[str] = mapped_column(Text)
    starts_at: Mapped[str] = mapped_column(Text, nullable=True)
    venue: Mapped[str] = mapped_column(Text, nullable=True)
    ticket_opens_at: Mapped[str] = mapped_column(Text, nullable=True)
    ticket_closes_at: Mapped[str] = mapped_column(Text, nullable=True)
    ticket_url: Mapped[str] = mapped_column(Text, nullable=True)
    price_text: Mapped[str] = mapped_column(Text, nullable=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, default="needs_review")
