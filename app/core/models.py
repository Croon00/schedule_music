from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


SourceType = Literal["x", "official_site", "ticket_site", "rss", "other"]
CandidateStatus = Literal["needs_review", "ready", "synced", "ignored"]


class ArtistCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    display_name: str | None = Field(default=None, max_length=120)
    notes: str | None = None
    x_username: str | None = Field(
        default=None,
        description="Optional X handle. Accepts '@artist' or 'artist'.",
    )

    @field_validator("x_username")
    @classmethod
    def normalize_x_username(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip().lstrip("@")
        return cleaned or None


class ArtistUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    display_name: str | None = Field(default=None, max_length=120)
    notes: str | None = None


class Artist(BaseModel):
    id: int
    name: str
    display_name: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class SourceCreate(BaseModel):
    source_type: SourceType
    value: str = Field(min_length=1, max_length=500)
    label: str | None = Field(default=None, max_length=120)
    is_active: bool = True

    @field_validator("value")
    @classmethod
    def normalize_value(cls, value: str) -> str:
        return value.strip()


class Source(BaseModel):
    id: int
    artist_id: int
    source_type: SourceType
    label: str | None
    value: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ArtistWithSources(Artist):
    sources: list[Source]


class EventCandidateCreate(BaseModel):
    artist_id: int | None = None
    source_id: int | None = None
    title: str = Field(min_length=1, max_length=200)
    starts_at: str | None = None
    venue: str | None = None
    ticket_opens_at: str | None = None
    ticket_url: str | None = None
    price_text: str | None = None
    source_url: str | None = None
    raw_text: str | None = None
    status: CandidateStatus = "needs_review"


class EventCandidate(EventCandidateCreate):
    id: int
    created_at: datetime
    updated_at: datetime
