from __future__ import annotations

from typing import Literal
from psycopg.types.json import Jsonb

from app.core.config import settings
from app.core.db import get_connection
from app.integrations.spotify import SpotifyTrackInfo, search_spotify_track, spotify_configured
from app.integrations.youtube_context import extract_lyrics_candidate, fetch_top_comment, fetch_video_description
from app.lyrics_pipeline.clients import OpenAiLyricsClient, OpenAiSpeechToTextClient, YouTubeTranscriptCaptionClient, YtDlpAudioDownloader
from app.lyrics_pipeline.models import LyricsInput, LyricsSourceType, RawLyrics
from app.lyrics_pipeline.service import LyricsPipeline, LyricsPipelineError
from app.lyrics_pipeline.youtube import canonical_youtube_watch_url, extract_youtube_video_id

SourceMode = Literal["caption", "description", "comment", "audio"]


async def _get_raw(youtube_url: str, mode: SourceMode, language: str) -> RawLyrics:
    video_id = extract_youtube_video_id(youtube_url)
    if mode == "audio":
        audio_path = await YtDlpAudioDownloader().download_audio(youtube_url)
        text = (await OpenAiSpeechToTextClient(language=language).transcribe(audio_path)).strip()
        if not text:
            raise LyricsPipelineError("음원 전사 결과가 비어 있습니다.")
        return RawLyrics(
            text=text,
            source_type=LyricsSourceType.AUDIO_TRANSCRIPT,
            language_code=language,
            source_url=youtube_url,
            needs_review=True,
        )
    if mode in {"description", "comment"}:
        context = await (fetch_video_description(video_id) if mode == "description" else fetch_top_comment(video_id))
        if context:
            result = await extract_lyrics_candidate(context.text, context.source)
            if result:
                return RawLyrics(
                    text=result[0],
                    source_type=LyricsSourceType.YOUTUBE_DESCRIPTION if mode == "description" else LyricsSourceType.YOUTUBE_COMMENT,
                    language_code=language,
                    source_url=youtube_url,
                    needs_review=True,
                )
        raise LyricsPipelineError("YouTube 설명 또는 댓글에서 가사 후보를 찾지 못했습니다.")

    pipeline = LyricsPipeline(
        caption_client=YouTubeTranscriptCaptionClient(),
        ai_client=OpenAiLyricsClient(),
        audio_downloader=None,
        speech_to_text_client=None,
    )
    return await pipeline.get_raw_lyrics(LyricsInput(
        youtube_url=youtube_url,
        preferred_languages=(language, "ja", "en", "ko"),
        allow_audio_fallback=False,
    ))


def _save(*, youtube_url: str, video_id: str, artist: str, title: str, raw: RawLyrics,
          translation: str, pronunciation: str, spotify: SpotifyTrackInfo | None) -> int:
    with get_connection() as conn:
        song_id = int(conn.execute(
            """
            INSERT INTO songs (
                discord_user_id, original_title, artist_name, album_name, release_date,
                language_code, duration_ms, youtube_url, youtube_video_id, spotify_track_id,
                spotify_url, spotify_album_id, spotify_artist_ids, cover_image_url, spotify_raw
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (discord_user_id, youtube_video_id) DO UPDATE SET
                original_title=EXCLUDED.original_title, artist_name=EXCLUDED.artist_name,
                album_name=EXCLUDED.album_name, release_date=EXCLUDED.release_date,
                language_code=EXCLUDED.language_code, duration_ms=EXCLUDED.duration_ms,
                spotify_track_id=EXCLUDED.spotify_track_id, spotify_url=EXCLUDED.spotify_url,
                spotify_album_id=EXCLUDED.spotify_album_id, spotify_artist_ids=EXCLUDED.spotify_artist_ids,
                cover_image_url=EXCLUDED.cover_image_url, spotify_raw=EXCLUDED.spotify_raw,
                updated_at=CURRENT_TIMESTAMP RETURNING id
            """,
            (
                "web", title, artist, spotify.album_name if spotify else None,
                spotify.release_date if spotify else None, raw.language_code,
                spotify.duration_ms if spotify else None, youtube_url, video_id,
                spotify.track_id if spotify else None, spotify.spotify_url if spotify else None,
                spotify.album_id if spotify else None, spotify.artist_ids if spotify else None,
                spotify.cover_image_url if spotify else None, Jsonb(spotify.raw) if spotify else None,
            ),
        ).fetchone()["id"])
        conn.execute(
            """
            INSERT INTO song_lyrics (song_id, original_lyrics, translation_ko, pronunciation_ko,
                lyrics_source_type, lyrics_source_url, translation_model, needs_review)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (song_id) DO UPDATE SET original_lyrics=EXCLUDED.original_lyrics,
                translation_ko=EXCLUDED.translation_ko, pronunciation_ko=EXCLUDED.pronunciation_ko,
                lyrics_source_type=EXCLUDED.lyrics_source_type, lyrics_source_url=EXCLUDED.lyrics_source_url,
                translation_model=EXCLUDED.translation_model, needs_review=EXCLUDED.needs_review,
                updated_at=CURRENT_TIMESTAMP
            """,
            (song_id, raw.text, translation, pronunciation, str(raw.source_type), raw.source_url, settings.openai_model, raw.needs_review),
        )
        conn.commit()
        return song_id


async def save_song_from_youtube(*, artist: str, title: str, youtube_url: str,
                                 source_mode: SourceMode, language_code: str = "ja") -> dict:
    video_id = extract_youtube_video_id(youtube_url)
    canonical_url = canonical_youtube_watch_url(youtube_url)
    raw = await _get_raw(canonical_url, source_mode, language_code.strip() or "ja")
    translation, pronunciation = await OpenAiLyricsClient().transform_lyrics(
        lyrics=raw.text, artist=artist, title=title
    )
    spotify = None
    if spotify_configured():
        try:
            spotify = await search_spotify_track(artist, title)
        except Exception:
            pass
    song_id = _save(youtube_url=canonical_url, video_id=video_id, artist=artist, title=title,
                    raw=raw, translation=translation, pronunciation=pronunciation, spotify=spotify)
    return {"id": song_id, "artist_name": artist, "title": title,
            "lyrics_source_type": str(raw.source_type), "needs_review": raw.needs_review,
            "spotify_track_id": spotify.track_id if spotify else None}
