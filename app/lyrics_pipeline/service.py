from __future__ import annotations

import logging
from pathlib import Path

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

logger = logging.getLogger(__name__)


class LyricsPipelineError(RuntimeError):
    """가사를 가져오거나 변환할 수 없을 때 발생하는 예외입니다."""


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
        try:
            caption = await self._fetch_best_caption(video_id, payload)
        except Exception:
            if not payload.allow_audio_fallback:
                raise
            logger.exception("자막 조회에 실패하여 오디오 전사 fallback으로 전환합니다.")
            caption = None
        if caption:
            return caption

        if payload.allow_audio_fallback:
            return await self._transcribe_audio(payload)

        raise LyricsPipelineError(
            "사용 가능한 업로더 자막이 없습니다. 오디오 fallback을 켜거나 가사를 직접 제공하세요."
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

    async def save_transform(
        self,
        *,
        payload: LyricsInput,
        output_path: str | Path,
    ) -> Path:
        transformed = await self.transform(payload)
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            self._format_transform_for_file(payload, transformed),
            encoding="utf-8",
        )
        return path

    def _format_transform_for_file(
        self,
        payload: LyricsInput,
        transformed: LyricsTransform,
    ) -> str:
        metadata = [
            f"제목: {payload.title or ''}",
            f"아티스트: {payload.artist or ''}",
            f"YouTube URL: {payload.youtube_url}",
            f"출처: {transformed.source_type}",
            f"검토 필요: {transformed.needs_review}",
        ]
        sections = [
            "\n".join(metadata).rstrip(),
            "## 원문\n\n" + transformed.original.strip(),
            "## 한국어 번역\n\n" + transformed.translation_ko.strip(),
            "## 한글 발음\n\n" + transformed.pronunciation_ko.strip(),
        ]
        return "\n\n".join(sections).rstrip() + "\n"

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
            raise LyricsPipelineError("오디오 fallback에는 다운로더와 음성-텍스트 클라이언트가 필요합니다.")

        audio_path = await self.audio_downloader.download_audio(payload.youtube_url)
        text = (await self.speech_to_text_client.transcribe(audio_path)).strip()
        if not text:
            raise LyricsPipelineError("오디오 전사 결과가 비어 있습니다.")

        return RawLyrics(
            text=text,
            source_type=LyricsSourceType.AUDIO_TRANSCRIPT,
            language_code=payload.preferred_languages[0] if payload.preferred_languages else None,
            source_url=payload.youtube_url,
            needs_review=True,
        )
