from __future__ import annotations

from pathlib import Path

import pytest

from app.lyrics_pipeline.models import CaptionTrack, LyricsInput, LyricsSourceType
from app.lyrics_pipeline.service import LyricsPipeline, LyricsPipelineError
from app.lyrics_pipeline.youtube import extract_youtube_video_id, normalize_caption_text


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


def test_extract_youtube_video_id_supports_common_urls() -> None:
    assert extract_youtube_video_id("https://youtu.be/abcdefghijk") == "abcdefghijk"
    assert extract_youtube_video_id("https://www.youtube.com/watch?v=abcdefghijk") == "abcdefghijk"
    assert extract_youtube_video_id("abcdefghijk") == "abcdefghijk"


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


@pytest.mark.anyio
async def test_pipeline_prefers_manual_uploader_caption() -> None:
    caption_client = FakeCaptionClient(
        tracks=[
            CaptionTrack("en", "English", is_generated=True),
            CaptionTrack("ja", "Japanese", is_generated=False),
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
            tracks=[CaptionTrack("ja", "Japanese", is_generated=True)],
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
            tracks=[CaptionTrack("ja", "Japanese", is_generated=False)],
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
            tracks=[CaptionTrack("ja", "Japanese", is_generated=False)],
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
    assert "Title: Title" in text
    assert "Artist: Artist" in text
    assert "## Original\n\nlyrics" in text
    assert "## Korean Translation\n\ntranslated: lyrics" in text
    assert "## Korean Pronunciation\n\npronounced: lyrics" in text
