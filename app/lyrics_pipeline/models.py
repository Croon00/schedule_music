from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class LyricsSourceType(StrEnum):
    YOUTUBE_CAPTION = "youtube_caption"
    YOUTUBE_DESCRIPTION = "youtube_description"
    YOUTUBE_COMMENT = "youtube_comment"
    AUDIO_TRANSCRIPT = "audio_transcript"
    USER_LYRICS = "user_lyrics"


@dataclass(frozen=True)
class CaptionTrack:
    language_code: str
    language_name: str
    is_generated: bool = False


@dataclass(frozen=True)
class LyricsInput:
    youtube_url: str
    artist: str | None = None
    title: str | None = None
    preferred_languages: tuple[str, ...] = ("ja", "en", "ko")
    allow_audio_fallback: bool = False


@dataclass(frozen=True)
class RawLyrics:
    text: str
    source_type: LyricsSourceType
    language_code: str | None = None
    source_url: str | None = None
    needs_review: bool = False


@dataclass(frozen=True)
class LyricsTransform:
    original: str
    translation_ko: str
    pronunciation_ko: str
    source_type: LyricsSourceType
    needs_review: bool


@dataclass(frozen=True)
class NamuWikiRender:
    text: str
    source_type: LyricsSourceType
    needs_review: bool
