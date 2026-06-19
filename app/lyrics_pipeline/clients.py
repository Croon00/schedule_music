from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from openai import AsyncOpenAI

from app.core.config import settings
from app.lyrics_pipeline.models import CaptionTrack


LYRICS_TRANSFORM_SCHEMA = {
    "name": "lyrics_transform",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "translation_ko": {"type": "string"},
            "pronunciation_ko": {"type": "string"},
        },
        "required": ["translation_ko", "pronunciation_ko"],
    },
    "strict": True,
}


class CaptionClient(Protocol):
    async def list_tracks(self, video_id: str) -> list[CaptionTrack]:
        """Return public caption tracks for a YouTube video."""

    async def fetch_track(self, video_id: str, language_code: str) -> str | None:
        """Return caption text for a language, or None when unavailable."""


class AudioDownloader(Protocol):
    async def download_audio(self, youtube_url: str) -> Path:
        """Download/extract audio and return a local file path."""


class SpeechToTextClient(Protocol):
    async def transcribe(self, audio_path: Path) -> str:
        """Transcribe a local audio file."""


class LyricsAiClient(Protocol):
    async def transform_lyrics(
        self,
        *,
        lyrics: str,
        artist: str | None,
        title: str | None,
    ) -> tuple[str, str]:
        """Return Korean translation and Korean pronunciation."""

    async def render_namuwiki(
        self,
        *,
        original: str,
        translation_ko: str,
        pronunciation_ko: str,
        format_example: str,
        artist: str | None,
        title: str | None,
    ) -> str:
        """Return NamuWiki markup."""


class YouTubeTranscriptCaptionClient:
    """Caption client backed by youtube-transcript-api.

    This dependency is intentionally optional so unit tests do not need network
    access or the package installed. Add youtube-transcript-api before using it
    in production.
    """

    async def list_tracks(self, video_id: str) -> list[CaptionTrack]:
        from youtube_transcript_api import YouTubeTranscriptApi

        transcript_list = YouTubeTranscriptApi().list(video_id)
        tracks: list[CaptionTrack] = []
        for transcript in transcript_list:
            tracks.append(
                CaptionTrack(
                    language_code=transcript.language_code,
                    language_name=transcript.language,
                    is_generated=transcript.is_generated,
                )
            )
        return tracks

    async def fetch_track(self, video_id: str, language_code: str) -> str | None:
        from youtube_transcript_api import YouTubeTranscriptApi

        from app.lyrics_pipeline.youtube import normalize_caption_text

        transcript_list = YouTubeTranscriptApi().list(video_id)
        transcript = transcript_list.find_transcript([language_code])
        return normalize_caption_text(transcript.fetch().to_raw_data())


class OpenAiLyricsClient:
    """Lyrics transformer backed by the OpenAI Chat Completions API."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self.api_key = api_key or settings.openai_api_key
        self.model = model or settings.openai_model

    async def transform_lyrics(
        self,
        *,
        lyrics: str,
        artist: str | None,
        title: str | None,
    ) -> tuple[str, str]:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured.")

        client = AsyncOpenAI(api_key=self.api_key)
        response = await client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Translate the provided short lyric excerpt into natural Korean "
                        "and provide Korean hangul pronunciation for the original. "
                        "Keep line breaks aligned with the input where practical. "
                        "Return only JSON fields that match the schema."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Artist: {artist or '(unknown)'}\n"
                        f"Title: {title or '(unknown)'}\n\n"
                        f"Lyrics excerpt:\n{lyrics}"
                    ),
                },
            ],
            response_format={"type": "json_schema", "json_schema": LYRICS_TRANSFORM_SCHEMA},
        )
        content = response.choices[0].message.content
        if not content:
            return "", ""

        data = json.loads(content)
        return data["translation_ko"], data["pronunciation_ko"]

    async def render_namuwiki(
        self,
        *,
        original: str,
        translation_ko: str,
        pronunciation_ko: str,
        format_example: str,
        artist: str | None,
        title: str | None,
    ) -> str:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured.")

        client = AsyncOpenAI(api_key=self.api_key)
        response = await client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Render the supplied lyric excerpt, Korean translation, and "
                        "Korean pronunciation using the user's NamuWiki format example. "
                        "Do not add unrelated commentary."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Artist: {artist or '(unknown)'}\n"
                        f"Title: {title or '(unknown)'}\n\n"
                        f"Format example:\n{format_example}\n\n"
                        f"Original:\n{original}\n\n"
                        f"Korean translation:\n{translation_ko}\n\n"
                        f"Korean pronunciation:\n{pronunciation_ko}"
                    ),
                },
            ],
        )
        return response.choices[0].message.content or ""
