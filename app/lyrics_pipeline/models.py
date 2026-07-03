from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class LyricsSourceType(StrEnum):
    YOUTUBE_CAPTION = "youtube_caption"
    YOUTUBE_DESCRIPTION = "youtube_description"
    YOUTUBE_COMMENT = "youtube_comment"
    AUDIO_TRANSCRIPT = "audio_transcript"
    USER_LYRICS = "user_lyrics"


class LyricsBaseModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class CaptionTrack(LyricsBaseModel):
    language_code: str = Field(min_length=1)
    language_name: str = Field(min_length=1)
    is_generated: bool = False


class LyricsInput(LyricsBaseModel):
    youtube_url: str = Field(min_length=1)
    artist: str | None = None
    title: str | None = None
    preferred_languages: tuple[str, ...] = ("ja", "en", "ko")
    allow_audio_fallback: bool = False


class RawLyrics(LyricsBaseModel):
    text: str = Field(min_length=1)
    source_type: LyricsSourceType
    language_code: str | None = None
    source_url: str | None = None
    needs_review: bool = False


class LyricsTransform(LyricsBaseModel):
    original: str
    translation_ko: str
    pronunciation_ko: str
    source_type: LyricsSourceType
    needs_review: bool


class NamuWikiRender(LyricsBaseModel):
    text: str
    source_type: LyricsSourceType
    needs_review: bool
