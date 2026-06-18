from __future__ import annotations

from app.lyrics_pipeline.clients import (
    AudioDownloader,
    CaptionClient,
    LyricsAiClient,
    SpeechToTextClient,
)
from app.lyrics_pipeline.models import (
    LyricsInput,
    LyricsSourceType,
    LyricsTransform,
    NamuWikiRender,
    RawLyrics,
)
from app.lyrics_pipeline.youtube import extract_youtube_video_id


class LyricsPipelineError(RuntimeError):
    """Raised when lyrics cannot be obtained or transformed."""


class LyricsPipeline:
    def __init__(
        self,
        *,
        caption_client: CaptionClient,
        ai_client: LyricsAiClient,
        audio_downloader: AudioDownloader | None = None,
        speech_to_text_client: SpeechToTextClient | None = None,
    ) -> None:
        self.caption_client = caption_client
        self.ai_client = ai_client
        self.audio_downloader = audio_downloader
        self.speech_to_text_client = speech_to_text_client

    async def get_raw_lyrics(self, payload: LyricsInput) -> RawLyrics:
        video_id = extract_youtube_video_id(payload.youtube_url)
        caption = await self._fetch_best_caption(video_id, payload)
        if caption:
            return caption

        if payload.allow_audio_fallback:
            return await self._transcribe_audio(payload)

        raise LyricsPipelineError(
            "No uploader caption was available. Enable audio fallback or provide lyrics manually."
        )

    async def transform(self, payload: LyricsInput) -> LyricsTransform:
        raw = await self.get_raw_lyrics(payload)
        translation_ko, pronunciation_ko = await self.ai_client.transform_lyrics(
            lyrics=raw.text,
            artist=payload.artist,
            title=payload.title,
        )
        return LyricsTransform(
            original=raw.text,
            translation_ko=translation_ko,
            pronunciation_ko=pronunciation_ko,
            source_type=raw.source_type,
            needs_review=raw.needs_review,
        )

    async def render_namuwiki(
        self,
        *,
        payload: LyricsInput,
        format_example: str,
    ) -> NamuWikiRender:
        transformed = await self.transform(payload)
        text = await self.ai_client.render_namuwiki(
            original=transformed.original,
            translation_ko=transformed.translation_ko,
            pronunciation_ko=transformed.pronunciation_ko,
            format_example=format_example,
            artist=payload.artist,
            title=payload.title,
        )
        return NamuWikiRender(
            text=text,
            source_type=transformed.source_type,
            needs_review=transformed.needs_review,
        )

    async def _fetch_best_caption(
        self,
        video_id: str,
        payload: LyricsInput,
    ) -> RawLyrics | None:
        tracks = await self.caption_client.list_tracks(video_id)
        manual_tracks = [track for track in tracks if not track.is_generated]
        by_language = {track.language_code: track for track in manual_tracks}

        for language_code in payload.preferred_languages:
            track = by_language.get(language_code)
            if not track:
                continue
            text = await self.caption_client.fetch_track(video_id, track.language_code)
            if text:
                return RawLyrics(
                    text=text,
                    source_type=LyricsSourceType.YOUTUBE_CAPTION,
                    language_code=track.language_code,
                    source_url=payload.youtube_url,
                    needs_review=False,
                )
        return None

    async def _transcribe_audio(self, payload: LyricsInput) -> RawLyrics:
        if not self.audio_downloader or not self.speech_to_text_client:
            raise LyricsPipelineError("Audio fallback requires downloader and speech-to-text clients.")

        audio_path = await self.audio_downloader.download_audio(payload.youtube_url)
        text = (await self.speech_to_text_client.transcribe(audio_path)).strip()
        if not text:
            raise LyricsPipelineError("Audio transcription returned no text.")

        return RawLyrics(
            text=text,
            source_type=LyricsSourceType.AUDIO_TRANSCRIPT,
            source_url=payload.youtube_url,
            needs_review=True,
        )

