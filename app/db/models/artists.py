from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.common import TimestampMixin


class ArtistModel(TimestampMixin, Base):
    __tablename__ = "artists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    discord_user_id: Mapped[str] = mapped_column(Text, nullable=True)
    name: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text, nullable=True)
    artist_kind: Mapped[str] = mapped_column(Text, default="vtuber")
    agency: Mapped[str] = mapped_column(Text, nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=True)
    show_in_spotify: Mapped[bool] = mapped_column(Boolean, default=True)
    show_in_lyrics: Mapped[bool] = mapped_column(Boolean, default=True)
    show_in_youtube_lives: Mapped[bool] = mapped_column(Boolean, default=True)
    spotify_sync_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    spotify_artist_id: Mapped[str] = mapped_column(Text, nullable=True)
    spotify_name: Mapped[str] = mapped_column(Text, nullable=True)
    spotify_image_url: Mapped[str] = mapped_column(Text, nullable=True)
    spotify_url: Mapped[str] = mapped_column(Text, nullable=True)

    sources: Mapped[list[ArtistSourceModel]] = relationship(
        back_populates="artist", cascade="all, delete-orphan"
    )


class ArtistSourceModel(TimestampMixin, Base):
    __tablename__ = "artist_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    artist_id: Mapped[int] = mapped_column(ForeignKey("artists.id", ondelete="CASCADE"))
    source_type: Mapped[str] = mapped_column(Text)
    label: Mapped[str] = mapped_column(Text, nullable=True)
    value: Mapped[str] = mapped_column(Text)
    external_user_id: Mapped[str] = mapped_column(Text, nullable=True)
    last_seen_external_id: Mapped[str] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    artist: Mapped[ArtistModel] = relationship(back_populates="sources")


class ArtistAgencyModel(Base):
    __tablename__ = "artist_agencies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
