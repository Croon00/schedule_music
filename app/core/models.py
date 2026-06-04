from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


SourceType = Literal["x", "official_site", "ticket_site", "rss", "other"]
CandidateStatus = Literal["needs_review", "ready", "synced", "ignored"]


class ArtistCreate(BaseModel):
    """아티스트 생성 API에서 받는 입력값입니다."""

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
        """X username 입력값에서 앞쪽 @와 공백을 제거합니다."""
        if value is None:
            return None
        cleaned = value.strip().lstrip("@")
        return cleaned or None


class ArtistUpdate(BaseModel):
    """아티스트 정보를 부분 수정할 때 받는 입력값입니다."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    display_name: str | None = Field(default=None, max_length=120)
    notes: str | None = None


class Artist(BaseModel):
    """DB에 저장된 아티스트 기본 정보를 API 응답으로 표현합니다."""

    id: int
    name: str
    display_name: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class SourceCreate(BaseModel):
    """아티스트에 새 출처를 추가할 때 받는 입력값입니다."""

    source_type: SourceType
    value: str = Field(min_length=1, max_length=500)
    label: str | None = Field(default=None, max_length=120)
    is_active: bool = True

    @field_validator("value")
    @classmethod
    def normalize_value(cls, value: str) -> str:
        """출처 URL 또는 username 앞뒤 공백을 제거합니다."""
        return value.strip()


class Source(BaseModel):
    """DB에 저장된 아티스트 출처 정보를 API 응답으로 표현합니다."""

    id: int
    artist_id: int
    source_type: SourceType
    label: str | None
    value: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ArtistWithSources(Artist):
    """아티스트 기본 정보에 연결된 출처 목록을 포함한 응답 모델입니다."""

    sources: list[Source]


class EventCandidateCreate(BaseModel):
    """수동 입력 또는 agent 추출로 만들어지는 일정 후보 입력값입니다."""

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
    """DB에 저장된 일정 후보 정보를 API 응답으로 표현합니다."""

    id: int
    created_at: datetime
    updated_at: datetime
