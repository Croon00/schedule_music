from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
import uuid
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


def _split_proxy_locations(value: str | None) -> list[str] | None:
    if not value:
        return None
    locations = [item.strip().lower() for item in value.split(",") if item.strip()]
    return locations or None


def _build_transcript_proxy_config():
    if settings.webshare_proxy_username and settings.webshare_proxy_password:
        from youtube_transcript_api.proxies import WebshareProxyConfig

        return WebshareProxyConfig(
            proxy_username=settings.webshare_proxy_username,
            proxy_password=settings.webshare_proxy_password,
            filter_ip_locations=_split_proxy_locations(settings.webshare_proxy_locations),
        )

    if settings.youtube_transcript_proxy_http_url or settings.youtube_transcript_proxy_https_url:
        from youtube_transcript_api.proxies import GenericProxyConfig

        return GenericProxyConfig(
            http_url=settings.youtube_transcript_proxy_http_url,
            https_url=settings.youtube_transcript_proxy_https_url,
        )

    return None


def _build_ytdlp_proxy_url() -> str | None:
    if settings.ytdlp_proxy_url:
        return settings.ytdlp_proxy_url
    if settings.youtube_transcript_proxy_https_url:
        return settings.youtube_transcript_proxy_https_url
    if settings.youtube_transcript_proxy_http_url:
        return settings.youtube_transcript_proxy_http_url
    if settings.webshare_proxy_username and settings.webshare_proxy_password:
        return (
            "http://"
            f"{settings.webshare_proxy_username}:{settings.webshare_proxy_password}"
            "@p.webshare.io:80"
        )
    return None


class CaptionClient(Protocol):
    async def list_tracks(self, video_id: str) -> list[CaptionTrack]:
        """YouTube 영상의 공개 자막 트랙 목록을 반환합니다."""

    async def fetch_track(self, video_id: str, language_code: str) -> str | None:
        """지정한 언어의 자막 텍스트를 반환하고, 없으면 None을 반환합니다."""


class AudioDownloader(Protocol):
    async def download_audio(self, youtube_url: str) -> Path:
        """오디오를 내려받거나 추출한 뒤 로컬 파일 경로를 반환합니다."""


class SpeechToTextClient(Protocol):
    async def transcribe(self, audio_path: Path) -> str:
        """로컬 오디오 파일을 텍스트로 전사합니다."""


class LyricsAiClient(Protocol):
    async def transform_lyrics(
        self,
        *,
        lyrics: str,
        artist: str | None,
        title: str | None,
    ) -> tuple[str, str]:
        """한국어 번역과 한글 발음을 반환합니다."""

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
        """나무위키 문법 문자열을 반환합니다."""


class YouTubeTranscriptCaptionClient:
    """youtube-transcript-api를 사용하는 YouTube 자막 클라이언트입니다."""

    def _api(self):
        from youtube_transcript_api import YouTubeTranscriptApi

        return YouTubeTranscriptApi(proxy_config=_build_transcript_proxy_config())

    async def list_tracks(self, video_id: str) -> list[CaptionTrack]:
        from youtube_transcript_api import YouTubeTranscriptApi

        transcript_list = self._api().list(video_id)
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

        transcript_list = self._api().list(video_id)
        transcript = transcript_list.find_transcript([language_code])
        return normalize_caption_text(transcript.fetch().to_raw_data())


class YtDlpAudioDownloader:
    """허가된 fallback 전사를 위해 yt-dlp로 짧은 오디오 구간을 내려받습니다."""

    def __init__(
        self,
        *,
        output_dir: str | Path = "exports/audio",
        max_seconds: int | None = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.max_seconds = max_seconds or settings.lyrics_audio_fallback_max_seconds

    async def download_audio(self, youtube_url: str) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        stem = f"audio_{uuid.uuid4().hex}"
        output_template = str(self.output_dir / f"{stem}.%(ext)s")
        command = [
            sys.executable,
            "-m",
            "yt_dlp",
            "--no-playlist",
            "--quiet",
            "--no-warnings",
            "-f",
            "bestaudio/best",
            "--extract-audio",
            "--audio-format",
            "mp3",
            "-o",
            output_template,
        ]
        proxy_url = _build_ytdlp_proxy_url()
        if proxy_url:
            command.extend(["--proxy", proxy_url])
        if self.max_seconds > 0:
            command.extend(
                [
                    "--download-sections",
                    f"*0-{self.max_seconds}",
                    "--force-keyframes-at-cuts",
                ]
            )
        command.append(youtube_url)

        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await process.communicate()
        if process.returncode != 0:
            error = stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(
                "오디오 다운로드에 실패했습니다. yt-dlp와 ffmpeg가 사용 가능한지 확인하세요. "
                f"{error}"
            )

        matches = sorted(self.output_dir.glob(f"{stem}.*"))
        if not matches:
            raise RuntimeError("오디오 다운로드는 끝났지만 출력 파일이 생성되지 않았습니다.")
        return matches[0]


class OpenAiSpeechToTextClient:
    """OpenAI 오디오 전사 API를 사용하는 음성-텍스트 클라이언트입니다."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        language: str | None = None,
    ) -> None:
        self.api_key = api_key or settings.openai_api_key
        self.model = model or settings.openai_audio_model
        self.language = language

    async def transcribe(self, audio_path: Path) -> str:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY가 설정되어 있지 않습니다.")

        client = AsyncOpenAI(api_key=self.api_key)
        with audio_path.open("rb") as audio_file:
            response = await client.audio.transcriptions.create(
                file=audio_file,
                model=self.model,
                language=self.language or "ja",
                response_format="text",
            )
        return str(response)


class OpenAiLyricsClient:
    """OpenAI Chat Completions API를 사용하는 가사 변환 클라이언트입니다."""

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
            raise RuntimeError("OPENAI_API_KEY가 설정되어 있지 않습니다.")

        client = AsyncOpenAI(api_key=self.api_key)
        response = await client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "제공된 짧은 가사 발췌문을 자연스러운 한국어로 번역하고, "
                        "원문의 한글식 발음을 제공하세요. 가능하면 입력 줄바꿈과 "
                        "출력 줄바꿈을 맞추세요. 스키마와 일치하는 JSON 필드만 반환하세요."
                    ),
                },
                {
                    "role": "system",
                    "content": (
                        "For pronunciation_ko, keep English words, English sentences, romanized text, "
                        "artist names, song titles, and proper nouns exactly as written in the original. "
                        "Do not convert English into Korean phonetic spelling. Only non-Latin lyrics, "
                        "such as Japanese or Chinese, should be written as Korean-style pronunciation."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"아티스트: {artist or '(알 수 없음)'}\n"
                        f"제목: {title or '(알 수 없음)'}\n\n"
                        f"가사 발췌:\n{lyrics}"
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
            raise RuntimeError("OPENAI_API_KEY가 설정되어 있지 않습니다.")

        client = AsyncOpenAI(api_key=self.api_key)
        response = await client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "제공된 가사 발췌문, 한국어 번역, 한글 발음을 사용자의 "
                        "나무위키 형식 예시에 맞춰 작성하세요. 관련 없는 설명은 추가하지 마세요."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"아티스트: {artist or '(알 수 없음)'}\n"
                        f"제목: {title or '(알 수 없음)'}\n\n"
                        f"형식 예시:\n{format_example}\n\n"
                        f"원문:\n{original}\n\n"
                        f"한국어 번역:\n{translation_ko}\n\n"
                        f"한글 발음:\n{pronunciation_ko}"
                    ),
                },
            ],
        )
        return response.choices[0].message.content or ""
