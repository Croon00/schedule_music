from __future__ import annotations

from pathlib import Path
from typing import Protocol

from app.lyrics_pipeline.models import CaptionTrack


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

        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
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

        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        transcript = transcript_list.find_transcript([language_code])
        return normalize_caption_text(transcript.fetch())

