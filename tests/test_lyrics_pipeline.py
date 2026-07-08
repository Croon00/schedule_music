from __future__ import annotations

from pathlib import Path

import pytest

from app.lyrics_pipeline.clients import YtDlpAudioDownloader
from app.lyrics_pipeline.models import CaptionTrack, LyricsInput, LyricsSourceType
from app.lyrics_pipeline.service import LyricsPipeline, LyricsPipelineError
from app.lyrics_pipeline.youtube import (
    canonical_youtube_watch_url,
    extract_youtube_video_id,
    normalize_caption_text,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class FakeCaptionClient:
    def __init__(self, tracks: list[CaptionTrack], captions: dict[str, str]) -> None:
        self.tracks = tracks
        self.captions = captions
        self.fetched: list[str] = []

    async def list_tracks(self, video_id: str) -> list[CaptionTrack]:
        return self.tracks

    async def fetch_track(self, video_id: str, language_code: str) -> str | None:
        self.fetched.append(language_code)
        return self.captions.get(language_code)


class FailingCaptionClient:
    async def list_tracks(self, video_id: str) -> list[CaptionTrack]:
        raise RuntimeError("자막 조회 실패")

    async def fetch_track(self, video_id: str, language_code: str) -> str | None:
        raise RuntimeError("자막 조회 실패")


class FakeAudioDownloader:
    def __init__(self) -> None:
        self.called = False

    async def download_audio(self, youtube_url: str) -> Path:
        self.called = True
        return Path("song.mp3")


class FakeSpeechToTextClient:
    async def transcribe(self, audio_path: Path) -> str:
        return "transcribed lyrics"


class FakeAiClient:
    async def transform_lyrics(
        self,
        *,
        lyrics: str,
        artist: str | None,
        title: str | None,
    ) -> tuple[str, str]:
        return (f"translated: {lyrics}", f"pronounced: {lyrics}")

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
        return f"{format_example}\n{artist} - {title}\n{original}\n{translation_ko}\n{pronunciation_ko}"


class FakeYtDlpAudioDownloader(YtDlpAudioDownloader):
    def __init__(self, *, direct_size: int, output_dir: Path, max_upload_mb: int = 1) -> None:
        super().__init__(
            output_dir=output_dir,
            prefer_direct_download=True,
            max_upload_mb=max_upload_mb,
        )
        self.direct_size = direct_size
        self.commands: list[list[str]] = []

    async def _download_with_command(self, command: list[str], stem: str) -> Path:
        self.commands.append(command)
        is_direct = "--extract-audio" not in command
        extension = "m4a" if is_direct else "mp3"
        path = self.output_dir / f"{stem}.{extension}"
        path.write_bytes(b"x" * (self.direct_size if is_direct else 10))
        return path


def test_extract_youtube_video_id_supports_common_urls() -> None:
    assert extract_youtube_video_id("https://youtu.be/abcdefghijk") == "abcdefghijk"
    assert extract_youtube_video_id("https://www.youtube.com/watch?v=abcdefghijk") == "abcdefghijk"
    assert extract_youtube_video_id("abcdefghijk") == "abcdefghijk"


def test_canonical_youtube_watch_url_strips_playlist_parameters() -> None:
    assert canonical_youtube_watch_url(
        "https://www.youtube.com/watch?v=g3BOD2J45Mk&list=PLCtVGYYv4sMvQTSp5Wsw7uthfSBGC1z2x&index=4"
    ) == "https://www.youtube.com/watch?v=g3BOD2J45Mk"


def test_normalize_caption_text_removes_empty_and_duplicate_lines() -> None:
    text = normalize_caption_text(
        [
            {"text": " hello   world "},
            {"text": "hello world"},
            {"text": ""},
            {"text": "second line"},
        ]
    )

    assert text == "hello world\nsecond line"


def test_ytdlp_audio_downloader_direct_command_avoids_ffmpeg_options(tmp_path: Path) -> None:
    downloader = YtDlpAudioDownloader(output_dir=tmp_path)
    command = downloader._direct_download_command(
        str(tmp_path / "audio.%(ext)s"),
        "https://www.youtube.com/watch?v=abcdefghijk",
    )

    assert "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best" in command
    assert "--extract-audio" not in command
    assert "--audio-format" not in command
    assert "--download-sections" not in command


@pytest.mark.anyio
async def test_ytdlp_audio_downloader_uses_direct_download_when_small(tmp_path: Path) -> None:
    downloader = FakeYtDlpAudioDownloader(direct_size=10, output_dir=tmp_path)

    path = await downloader.download_audio(
        "https://www.youtube.com/watch?v=abcdefghijk&list=playlist&index=4"
    )

    assert path.suffix == ".m4a"
    assert len(downloader.commands) == 1
    assert downloader.commands[0][-1] == "https://www.youtube.com/watch?v=abcdefghijk"


@pytest.mark.anyio
async def test_ytdlp_audio_downloader_falls_back_when_direct_file_is_too_large(
    tmp_path: Path,
) -> None:
    downloader = FakeYtDlpAudioDownloader(
        direct_size=(2 * 1024 * 1024),
        output_dir=tmp_path,
        max_upload_mb=1,
    )

    path = await downloader.download_audio("https://www.youtube.com/watch?v=abcdefghijk")

    assert path.suffix == ".mp3"
    assert len(downloader.commands) == 2
    assert "--extract-audio" in downloader.commands[1]


@pytest.mark.anyio
async def test_pipeline_prefers_manual_uploader_caption() -> None:
    caption_client = FakeCaptionClient(
        tracks=[
            CaptionTrack(language_code="en", language_name="English", is_generated=True),
            CaptionTrack(language_code="ja", language_name="Japanese", is_generated=False),
        ],
        captions={"ja": "manual lyrics"},
    )
    pipeline = LyricsPipeline(caption_client=caption_client, ai_client=FakeAiClient())

    result = await pipeline.transform(
        LyricsInput(
            youtube_url="https://www.youtube.com/watch?v=abcdefghijk",
            artist="Artist",
            title="Song",
        )
    )

    assert result.original == "manual lyrics"
    assert result.translation_ko == "translated: manual lyrics"
    assert result.source_type == LyricsSourceType.YOUTUBE_CAPTION
    assert result.needs_review is False
    assert caption_client.fetched == ["ja"]


@pytest.mark.anyio
async def test_pipeline_falls_back_to_audio_when_no_manual_caption() -> None:
    downloader = FakeAudioDownloader()
    pipeline = LyricsPipeline(
        caption_client=FakeCaptionClient(
            tracks=[CaptionTrack(language_code="ja", language_name="Japanese", is_generated=True)],
            captions={"ja": "generated captions should be ignored"},
        ),
        ai_client=FakeAiClient(),
        audio_downloader=downloader,
        speech_to_text_client=FakeSpeechToTextClient(),
    )

    result = await pipeline.transform(
        LyricsInput(
            youtube_url="https://www.youtube.com/watch?v=abcdefghijk",
            allow_audio_fallback=True,
        )
    )

    assert downloader.called is True
    assert result.original == "transcribed lyrics"
    assert result.source_type == LyricsSourceType.AUDIO_TRANSCRIPT
    assert result.needs_review is True


@pytest.mark.anyio
async def test_pipeline_falls_back_to_audio_when_caption_lookup_fails() -> None:
    downloader = FakeAudioDownloader()
    pipeline = LyricsPipeline(
        caption_client=FailingCaptionClient(),
        ai_client=FakeAiClient(),
        audio_downloader=downloader,
        speech_to_text_client=FakeSpeechToTextClient(),
    )

    result = await pipeline.transform(
        LyricsInput(
            youtube_url="https://www.youtube.com/watch?v=abcdefghijk",
            allow_audio_fallback=True,
        )
    )

    assert downloader.called is True
    assert result.original == "transcribed lyrics"
    assert result.source_type == LyricsSourceType.AUDIO_TRANSCRIPT
    assert result.needs_review is True


@pytest.mark.anyio
async def test_pipeline_errors_without_caption_or_audio_fallback() -> None:
    pipeline = LyricsPipeline(
        caption_client=FakeCaptionClient(tracks=[], captions={}),
        ai_client=FakeAiClient(),
    )

    with pytest.raises(LyricsPipelineError):
        await pipeline.transform(
            LyricsInput(youtube_url="https://www.youtube.com/watch?v=abcdefghijk")
        )


@pytest.mark.anyio
async def test_pipeline_renders_namuwiki_markup() -> None:
    pipeline = LyricsPipeline(
        caption_client=FakeCaptionClient(
            tracks=[CaptionTrack(language_code="ja", language_name="Japanese", is_generated=False)],
            captions={"ja": "lyrics"},
        ),
        ai_client=FakeAiClient(),
    )

    result = await pipeline.render_namuwiki(
        payload=LyricsInput(
            youtube_url="https://www.youtube.com/watch?v=abcdefghijk",
            artist="Artist",
            title="Song",
        ),
        format_example="== Lyrics ==",
    )

    assert "== Lyrics ==" in result.text
    assert "Artist - Song" in result.text
    assert result.source_type == LyricsSourceType.YOUTUBE_CAPTION


@pytest.mark.anyio
async def test_pipeline_saves_transformed_lyrics(tmp_path: Path) -> None:
    pipeline = LyricsPipeline(
        caption_client=FakeCaptionClient(
            tracks=[CaptionTrack(language_code="ja", language_name="Japanese", is_generated=False)],
            captions={"ja": "lyrics"},
        ),
        ai_client=FakeAiClient(),
    )
    output_path = tmp_path / "exports" / "lyrics.txt"

    saved_path = await pipeline.save_transform(
        payload=LyricsInput(
            youtube_url="https://www.youtube.com/watch?v=abcdefghijk",
            artist="Artist",
            title="Title",
        ),
        output_path=output_path,
    )

    assert saved_path == output_path
    text = output_path.read_text(encoding="utf-8")
    assert "제목: Title" in text
    assert "아티스트: Artist" in text
    assert "## 원문\n\nlyrics" in text
    assert "## 한국어 번역\n\ntranslated: lyrics" in text
    assert "## 한글 발음\n\npronounced: lyrics" in text
