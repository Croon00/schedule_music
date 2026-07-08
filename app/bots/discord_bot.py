from __future__ import annotations

from itertools import zip_longest
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import discord
from discord import app_commands
from psycopg.types.json import Jsonb
from youtube_transcript_api._errors import YouTubeTranscriptApiException

from app.core.config import settings
from app.core.db import get_connection, init_db, row_to_dict
from app.integrations.google_calendar import (
    build_google_auth_url,
    google_connected,
    google_oauth_configured,
)
from app.integrations.notifications import (
    NotificationRouteConflictError,
    NotificationRouteNotFoundError,
    create_notification_route,
    delete_notification_route,
    get_notification_route,
    list_notification_routes,
)
from app.integrations.spotify import SpotifyTrackInfo, search_spotify_track, spotify_configured
from app.integrations.youtube_context import (
    extract_lyrics_candidate,
    fetch_top_comment,
    fetch_video_description,
)
from app.lyrics_pipeline.clients import (
    OpenAiLyricsClient,
    OpenAiSpeechToTextClient,
    YouTubeTranscriptCaptionClient,
    YtDlpAudioDownloader,
)
from app.lyrics_pipeline.models import LyricsInput, LyricsSourceType, RawLyrics
from app.lyrics_pipeline.service import LyricsPipeline, LyricsPipelineError
from app.lyrics_pipeline.youtube import canonical_youtube_watch_url, extract_youtube_video_id
from app.namuwiki.ai_renderer import NamuWikiAiRenderError, render_song_article_from_template
from app.namuwiki.models import (
    NamuWikiCredit,
    NamuWikiLyricLine,
    NamuWikiSongArticleRequest,
    NamuWikiTemplateCreate,
    NamuWikiTemplateSongArticleRequest,
)
from app.namuwiki.template_store import (
    NamuWikiTemplateNotFoundError,
    get_template,
    list_templates,
    save_template,
)

logger = logging.getLogger(__name__)

LYRICS_SAMPLE_MAX_CHARS = 15000
LYRICS_SAMPLE_MAX_LINES = 15000
LYRICS_EXPORT_DIR = Path("exports")
NAMUWIKI_EXPORT_DIR = Path("exports") / "namuwiki"
SONG_EXPORT_DIR = Path("exports") / "songs"
NAMUWIKI_FIELD_MAX_CHARS = 500
LyricsSourceMode = Literal["description", "comment", "caption", "audio", "manual"]


class _NoopLyricsAiClient:
    async def transform_lyrics(
        self,
        *,
        lyrics: str,
        artist: str | None,
        title: str | None,
    ) -> tuple[str, str]:
        return "", ""

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
        return format_example


def _normalize_x_username(value: str) -> str:
    """Discord 입력값에서 앞쪽 @와 공백을 제거해 X username만 남깁니다."""
    return value.strip().lstrip("@")


def _caption_sample(text: str) -> str:
    lines: list[str] = []
    used_chars = 0
    for line in (line.strip() for line in text.splitlines()):
        if not line:
            continue
        remaining = LYRICS_SAMPLE_MAX_CHARS - used_chars
        if remaining <= 0 or len(lines) >= LYRICS_SAMPLE_MAX_LINES:
            break
        if len(line) > remaining:
            line = line[:remaining].rstrip()
        lines.append(line)
        used_chars += len(line)
    return "\n".join(lines)


def _caption_report(
    *,
    youtube_url: str,
    tracks: list,
    raw: RawLyrics,
    translation_ko: str | None = None,
    pronunciation_ko: str | None = None,
) -> str:
    raw_lines = [line for line in raw.text.splitlines() if line.strip()]
    track_lines = [
        f"- {track.language_code} {track.language_name} generated={track.is_generated}"
        for track in tracks
    ]
    available_captions = chr(10).join(track_lines) if track_lines else "- none"
    diagnostic_lines = []
    if raw.source_url:
        diagnostic_lines.append(f"- source_url: {raw.source_url}")
    diagnostic_lines.extend(
        f"- {key}: {value}"
        for key, value in raw.diagnostics.items()
        if value is not None
    )
    sections = [
        f"URL: {youtube_url}",
        f"선택된 출처: {raw.source_type}",
        f"선택된 언어: {raw.language_code}",
        f"검토 필요: {raw.needs_review}",
        f"원문 자막 길이: {len(raw.text)}자 / {len(raw_lines)}줄",
        "",
        "사용 가능한 자막",
        available_captions,
        "",
        "## 원문",
        "",
        _caption_sample(raw.text),
    ]
    if diagnostic_lines:
        sections.extend(["", "## Diagnostics", "", "\n".join(diagnostic_lines)])
    if translation_ko is not None:
        sections.extend(["", "## 한국어 번역", "", translation_ko])
    if pronunciation_ko is not None:
        sections.extend(["", "## 한국어 발음", "", pronunciation_ko])
    return "\n".join(sections).rstrip() + "\n"


async def _transform_caption_preview(raw: RawLyrics) -> tuple[str | None, str | None]:
    if not settings.openai_api_key:
        return None, None

    preview = _caption_sample(raw.text)
    if not preview:
        return None, None

    ai_client = OpenAiLyricsClient()
    return await ai_client.transform_lyrics(
        lyrics=preview,
        artist=None,
        title=None,
    )


async def _fetch_context_lyrics_candidate(
    *,
    video_id: str,
    youtube_url: str,
    use_description: bool,
    use_comment: bool,
    language_code: str,
) -> RawLyrics | None:
    candidates = []
    if use_description:
        description = await fetch_video_description(video_id)
        if description:
            candidates.append((LyricsSourceType.YOUTUBE_DESCRIPTION, description))
    if use_comment:
        comment = await fetch_top_comment(video_id)
        if comment:
            candidates.append((LyricsSourceType.YOUTUBE_COMMENT, comment))

    for source_type, candidate in candidates:
        extracted = await extract_lyrics_candidate(candidate.text, candidate.source)
        if not extracted:
            continue
        excerpt, _reason = extracted
        return RawLyrics(
            text=excerpt,
            source_type=source_type,
            language_code=language_code,
            source_url=youtube_url,
            needs_review=True,
        )
    return None


def _lyrics_pipeline_for_source(
    *,
    language_code: str,
    audio_enabled: bool,
) -> LyricsPipeline:
    return LyricsPipeline(
        caption_client=YouTubeTranscriptCaptionClient(),
        ai_client=_NoopLyricsAiClient(),
        audio_downloader=YtDlpAudioDownloader() if audio_enabled else None,
        speech_to_text_client=(
            OpenAiSpeechToTextClient(language=language_code.strip() or "ja")
            if audio_enabled
            else None
        ),
    )


async def _collect_raw_lyrics_from_youtube(
    *,
    youtube_url: str,
    language_code: str,
    source_mode: LyricsSourceMode,
) -> RawLyrics:
    video_id = extract_youtube_video_id(youtube_url)
    normalized_language = language_code.strip() or "ja"
    pipeline = _lyrics_pipeline_for_source(
        language_code=normalized_language,
        audio_enabled=source_mode == "audio",
    )

    if source_mode == "description":
        raw = await _fetch_context_lyrics_candidate(
            video_id=video_id,
            youtube_url=youtube_url,
            use_description=True,
            use_comment=False,
            language_code=normalized_language,
        )
        if raw:
            return raw
        raise LyricsPipelineError("설명란에서 가사 후보를 찾을 수 없습니다.")

    if source_mode == "comment":
        raw = await _fetch_context_lyrics_candidate(
            video_id=video_id,
            youtube_url=youtube_url,
            use_description=False,
            use_comment=True,
            language_code=normalized_language,
        )
        if raw:
            return raw
        raise LyricsPipelineError("상단 댓글에서 가사 후보를 찾을 수 없습니다.")

    if source_mode == "caption":
        return await pipeline.get_raw_lyrics(
            LyricsInput(
                youtube_url=youtube_url,
                preferred_languages=(normalized_language, "ja", "en", "ko"),
                allow_audio_fallback=False,
            )
        )

    if source_mode == "audio":
        audio_path = await YtDlpAudioDownloader().download_audio(youtube_url)
        text = (await OpenAiSpeechToTextClient(language=normalized_language).transcribe(audio_path)).strip()
        if not text:
            raise LyricsPipelineError("오디오 전사 결과가 비어 있습니다.")
        canonical_url = canonical_youtube_watch_url(youtube_url)
        return RawLyrics(
            text=text,
            source_type=LyricsSourceType.AUDIO_TRANSCRIPT,
            language_code=normalized_language,
            source_url=canonical_url,
            needs_review=True,
            diagnostics={
                "requested_youtube_url": youtube_url,
                "canonical_youtube_url": canonical_url,
                "audio_file": str(audio_path),
                "audio_file_name": audio_path.name,
                "audio_file_size_bytes": str(audio_path.stat().st_size),
            },
        )

    raise LyricsPipelineError("지원하지 않는 YouTube 가사 소스입니다.")


def _raw_lyrics_from_manual_text(
    *,
    text: str | None,
    language_code: str,
    source_url: str | None,
) -> RawLyrics:
    if not text or not text.strip():
        raise LyricsPipelineError("manual source_mode에는 lyrics 값이 필요합니다.")
    return RawLyrics(
        text=text.strip(),
        source_type=LyricsSourceType.USER_LYRICS,
        language_code=language_code.strip() or "ja",
        source_url=source_url,
        needs_review=False,
    )


def _openai_status_text(
    translation_ko: str | None,
    pronunciation_ko: str | None,
    error: str | None = None,
) -> str:
    if error:
        return f"OpenAI 미리보기 변환: `실패 ({error})`"
    if translation_ko is None and pronunciation_ko is None:
        return "OpenAI 미리보기 변환: `건너뜀 (OPENAI_API_KEY 미설정)`"
    return "OpenAI 미리보기 변환: `완료`"


def _caption_report_path(video_id: str, discord_user_id: str) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    return LYRICS_EXPORT_DIR / f"{video_id}_{discord_user_id}_{timestamp}_caption_report.txt"


def _namuwiki_article_path(title: str, discord_user_id: str) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    safe_title = "".join(ch if ch.isalnum() else "_" for ch in title).strip("_") or "article"
    return NAMUWIKI_EXPORT_DIR / f"{safe_title}_{discord_user_id}_{timestamp}.txt"


def _song_lyrics_export_path(
    song_id: int,
    title: str,
    discord_user_id: str,
    part: str | None = None,
) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    safe_title = "".join(ch if ch.isalnum() else "_" for ch in title).strip("_") or "song"
    part_suffix = f"_{part}" if part else ""
    return SONG_EXPORT_DIR / f"song_{song_id}_{safe_title}{part_suffix}_{discord_user_id}_{timestamp}.txt"


def _template_text_from_inputs(
    template_text: str | None,
    template_file_text: str | None,
) -> str:
    text = (template_file_text or template_text or "").strip()
    if not text:
        raise ValueError("템플릿 본문 또는 템플릿 txt 파일이 필요합니다.")
    return text


def _split_nonempty_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _truncate_namuwiki_field(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    return value[:NAMUWIKI_FIELD_MAX_CHARS]


def _build_lyric_lines(
    original: str,
    pronunciation_ko: str,
    translation_ko: str,
) -> list[NamuWikiLyricLine]:
    lines = []
    for original_line, pronunciation_line, translation_line in zip_longest(
        _split_nonempty_lines(original),
        _split_nonempty_lines(pronunciation_ko),
        _split_nonempty_lines(translation_ko),
        fillvalue=None,
    ):
        lines.append(
            NamuWikiLyricLine(
                original=_truncate_namuwiki_field(original_line),
                pronunciation_ko=_truncate_namuwiki_field(pronunciation_line),
                translation_ko=_truncate_namuwiki_field(translation_line),
            )
        )
    return lines


def _parse_namuwiki_extra_credits(value: str | None) -> list[NamuWikiCredit]:
    if not value or not value.strip():
        return []

    credits: list[NamuWikiCredit] = []
    raw_parts = value.replace("\n", ";").split(";")
    for raw_part in raw_parts:
        part = raw_part.strip()
        if not part:
            continue

        separator = "=" if "=" in part else ":" if ":" in part else None
        if separator is None:
            raise ValueError("extra_credits must use 'role=name' entries separated by ';'.")

        role, raw_name = (piece.strip() for piece in part.split(separator, 1))
        if not role or not raw_name:
            raise ValueError("extra_credits entries need both role and name.")

        name, _, name_ko = raw_name.partition("|")
        credits.append(
            NamuWikiCredit(
                role=role,
                name=name.strip(),
                name_ko=name_ko.strip() or None,
            )
        )

    return credits


async def _fetch_template_attachment_text(template_file: discord.Attachment | None) -> str | None:
    if template_file is None:
        return None
    raw = await template_file.read()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("템플릿 파일은 UTF-8 txt 파일이어야 합니다.") from exc


async def _collect_raw_lyrics_for_namuwiki(
    *,
    youtube_url: str,
    language_code: str,
    source_mode: LyricsSourceMode,
    manual_lyrics: str | None = None,
) -> RawLyrics:
    if source_mode == "manual":
        return _raw_lyrics_from_manual_text(
            text=manual_lyrics,
            language_code=language_code,
            source_url=youtube_url,
        )
    return await _collect_raw_lyrics_from_youtube(
        youtube_url=youtube_url,
        language_code=language_code,
        source_mode=source_mode,
    )


async def _fetch_text_attachment_text(attachment: discord.Attachment | None, label: str) -> str | None:
    if attachment is None:
        return None
    raw = await attachment.read()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{label} 파일은 UTF-8 txt 파일이어야 합니다.") from exc


def _create_artist(
    discord_user_id: str,
    name: str,
    x_username: str,
    display_name: str | None,
    notes: str | None,
) -> dict:
    """Discord 사용자 계정에 연결된 아티스트와 X 출처를 DB에 함께 등록합니다."""
    normalized_x_username = _normalize_x_username(x_username)
    if not normalized_x_username:
        raise ValueError("X 사용자명은 필수입니다.")

    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO artists (discord_user_id, name, display_name, notes)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (discord_user_id, name.strip(), display_name, notes),
        )
        artist_id = cursor.fetchone()["id"]
        conn.execute(
            """
            INSERT INTO artist_sources (artist_id, source_type, label, value)
            VALUES (%s, 'x', 'X account', %s)
            """,
            (artist_id, normalized_x_username),
        )
        conn.commit()

        return row_to_dict(
            conn.execute("SELECT * FROM artists WHERE id = %s", (artist_id,)).fetchone()
        )


def _delete_artist(discord_user_id: str, artist_id: int) -> bool:
    """요청한 Discord 사용자가 소유한 아티스트만 삭제합니다."""
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM artists WHERE id = %s AND discord_user_id = %s",
            (artist_id, discord_user_id),
        )
        conn.commit()
        return cursor.rowcount > 0


def _list_artists(discord_user_id: str) -> list[dict]:
    """Discord 사용자에게 등록된 아티스트와 대표 X username 목록을 조회합니다."""
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT
                a.id,
                a.name,
                a.display_name,
                s.value AS x_username
            FROM artists a
            LEFT JOIN artist_sources s
                ON s.artist_id = a.id AND s.source_type = 'x'
            WHERE a.discord_user_id = %s
            ORDER BY a.name
            LIMIT 25
            """,
            (discord_user_id,),
        ).fetchall()


def _list_sources_for_user(discord_user_id: str) -> list[dict]:
    """현재 Discord 사용자가 등록한 아티스트 소스와 source_id를 조회합니다."""
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT
                s.id,
                s.source_type,
                s.label,
                s.value,
                s.is_active,
                a.name AS artist_name,
                a.display_name
            FROM artist_sources s
            JOIN artists a ON a.id = s.artist_id
            WHERE a.discord_user_id = %s
            ORDER BY a.name, s.source_type, s.value
            LIMIT 50
            """,
            (discord_user_id,),
        ).fetchall()


def _format_route(route: dict) -> str:
    """Discord route 한 줄을 사람이 읽기 쉬운 형태로 바꿉니다."""
    source = route.get("source_value") or "전체 소스"
    artist = route.get("artist_name")
    artist_prefix = f"{artist} / " if artist else ""
    active_suffix = "" if route.get("is_active", True) else " (비활성)"
    return (
        f"#{route['id']} `{route['item_type']}` "
        f"{artist_prefix}{source} -> <#{route['discord_channel_id']}>{active_suffix}"
    )


def _guild_id_from_interaction(interaction: discord.Interaction) -> str:
    """라우팅 명령어가 DM이 아니라 서버에서 실행됐는지 확인합니다."""
    if interaction.guild_id is None:
        raise ValueError("라우팅 설정은 Discord 서버 안에서만 사용할 수 있습니다.")
    return str(interaction.guild_id)


def _ensure_manage_guild(interaction: discord.Interaction) -> None:
    """서버 라우팅 설정은 서버 관리 권한이 있는 사용자만 변경하게 합니다."""
    permissions = getattr(interaction.user, "guild_permissions", None)
    if permissions is None or not permissions.manage_guild:
        raise PermissionError("서버 관리 권한이 있는 사용자만 라우팅을 설정할 수 있습니다.")


def _save_song_with_lyrics(
    *,
    discord_user_id: str,
    youtube_url: str,
    youtube_video_id: str,
    artist_name: str,
    original_title: str,
    title_ko: str | None,
    artist_name_ko: str | None,
    raw: RawLyrics,
    translation_ko: str,
    pronunciation_ko: str,
    spotify: SpotifyTrackInfo | None,
) -> int:
    """곡 메타데이터와 원문/번역/발음을 DB에 저장하고 song id를 반환합니다."""
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO songs (
                discord_user_id, original_title, title_ko, artist_name, artist_name_ko,
                album_name, release_date, language_code, duration_ms,
                youtube_url, youtube_video_id, spotify_track_id, spotify_url,
                spotify_album_id, spotify_artist_ids, cover_image_url, spotify_raw
            )
            VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s
            )
            ON CONFLICT (discord_user_id, youtube_video_id) DO UPDATE SET
                original_title = EXCLUDED.original_title,
                title_ko = EXCLUDED.title_ko,
                artist_name = EXCLUDED.artist_name,
                artist_name_ko = EXCLUDED.artist_name_ko,
                album_name = EXCLUDED.album_name,
                release_date = EXCLUDED.release_date,
                language_code = EXCLUDED.language_code,
                duration_ms = EXCLUDED.duration_ms,
                youtube_url = EXCLUDED.youtube_url,
                spotify_track_id = EXCLUDED.spotify_track_id,
                spotify_url = EXCLUDED.spotify_url,
                spotify_album_id = EXCLUDED.spotify_album_id,
                spotify_artist_ids = EXCLUDED.spotify_artist_ids,
                cover_image_url = EXCLUDED.cover_image_url,
                spotify_raw = EXCLUDED.spotify_raw,
                updated_at = CURRENT_TIMESTAMP
            RETURNING id
            """,
            (
                discord_user_id,
                original_title,
                title_ko,
                artist_name,
                artist_name_ko,
                spotify.album_name if spotify else None,
                spotify.release_date if spotify else None,
                raw.language_code,
                spotify.duration_ms if spotify else None,
                youtube_url,
                youtube_video_id,
                spotify.track_id if spotify else None,
                spotify.spotify_url if spotify else None,
                spotify.album_id if spotify else None,
                spotify.artist_ids if spotify else None,
                spotify.cover_image_url if spotify else None,
                Jsonb(spotify.raw) if spotify else None,
            ),
        )
        song_id = cursor.fetchone()["id"]
        conn.execute(
            """
            INSERT INTO song_lyrics (
                song_id, original_lyrics, translation_ko, pronunciation_ko,
                lyrics_source_type, lyrics_source_url, translation_model, needs_review
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (song_id) DO UPDATE SET
                original_lyrics = EXCLUDED.original_lyrics,
                translation_ko = EXCLUDED.translation_ko,
                pronunciation_ko = EXCLUDED.pronunciation_ko,
                lyrics_source_type = EXCLUDED.lyrics_source_type,
                lyrics_source_url = EXCLUDED.lyrics_source_url,
                translation_model = EXCLUDED.translation_model,
                needs_review = EXCLUDED.needs_review,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                song_id,
                raw.text,
                translation_ko,
                pronunciation_ko,
                str(raw.source_type),
                raw.source_url,
                settings.openai_model,
                raw.needs_review,
            ),
        )
        conn.commit()
        return int(song_id)


def _song_select_columns() -> str:
    return """
        s.id,
        s.original_title,
        s.title_ko,
        s.artist_name,
        s.artist_name_ko,
        s.album_name,
        s.release_date,
        s.language_code,
        s.duration_ms,
        s.youtube_url,
        s.youtube_video_id,
        s.spotify_url,
        s.cover_image_url,
        s.created_at,
        s.updated_at,
        l.original_lyrics,
        l.translation_ko,
        l.pronunciation_ko,
        l.lyrics_source_type,
        l.lyrics_source_url,
        l.translation_model,
        l.needs_review,
        l.review_notes,
        l.reviewed_at
    """


def _find_songs(discord_user_id: str, artist: str, title: str, limit: int = 5) -> list[dict]:
    artist_query = artist.strip()
    title_query = title.strip()
    if not artist_query or not title_query:
        raise ValueError("artist와 title을 모두 입력해야 합니다.")

    exact_sql = f"""
        SELECT {_song_select_columns()}
        FROM songs s
        JOIN song_lyrics l ON l.song_id = s.id
        WHERE s.discord_user_id = %s
          AND (
            lower(s.artist_name) = lower(%s)
            OR lower(coalesce(s.artist_name_ko, '')) = lower(%s)
          )
          AND (
            lower(s.original_title) = lower(%s)
            OR lower(coalesce(s.title_ko, '')) = lower(%s)
          )
        ORDER BY s.updated_at DESC
        LIMIT %s
    """
    fuzzy_sql = f"""
        SELECT {_song_select_columns()}
        FROM songs s
        JOIN song_lyrics l ON l.song_id = s.id
        WHERE s.discord_user_id = %s
          AND (
            s.artist_name ILIKE %s
            OR coalesce(s.artist_name_ko, '') ILIKE %s
          )
          AND (
            s.original_title ILIKE %s
            OR coalesce(s.title_ko, '') ILIKE %s
          )
        ORDER BY s.updated_at DESC
        LIMIT %s
    """
    with get_connection() as conn:
        rows = conn.execute(
            exact_sql,
            (discord_user_id, artist_query, artist_query, title_query, title_query, limit),
        ).fetchall()
        if rows:
            return [dict(row) for row in rows]

        artist_like = f"%{artist_query}%"
        title_like = f"%{title_query}%"
        rows = conn.execute(
            fuzzy_sql,
            (discord_user_id, artist_like, artist_like, title_like, title_like, limit),
        ).fetchall()
        return [dict(row) for row in rows]


def _get_song_by_id(discord_user_id: str, song_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            f"""
            SELECT {_song_select_columns()}
            FROM songs s
            JOIN song_lyrics l ON l.song_id = s.id
            WHERE s.discord_user_id = %s AND s.id = %s
            """,
            (discord_user_id, song_id),
        ).fetchone()
        return row_to_dict(row)


def _format_song_summary(song: dict) -> str:
    title_ko = f" / {song['title_ko']}" if song.get("title_ko") else ""
    artist_ko = f" / {song['artist_name_ko']}" if song.get("artist_name_ko") else ""
    album = song.get("album_name") or "-"
    release_date = song.get("release_date") or "-"
    spotify_url = song.get("spotify_url") or "-"
    review = "필요" if song.get("needs_review") else "완료"
    return "\n".join(
        [
            f"song #{song['id']}",
            f"제목: {song['original_title']}{title_ko}",
            f"아티스트: {song['artist_name']}{artist_ko}",
            f"앨범: {album}",
            f"발매일: {release_date}",
            f"YouTube: {song['youtube_url']}",
            f"Spotify: {spotify_url}",
            f"가사 출처: `{song['lyrics_source_type']}` / 검토: `{review}`",
        ]
    )


def _format_song_candidates(songs: list[dict]) -> str:
    lines = ["여러 곡이 검색되었습니다. 정확한 곡은 `/song_show_by_id`로 확인해주세요."]
    for song in songs:
        title_ko = f" / {song['title_ko']}" if song.get("title_ko") else ""
        artist_ko = f" / {song['artist_name_ko']}" if song.get("artist_name_ko") else ""
        lines.append(f"#{song['id']} {song['artist_name']}{artist_ko} - {song['original_title']}{title_ko}")
    return "\n".join(lines)


def _song_lyrics_export_text(song: dict) -> str:
    sections = [
        _format_song_summary(song),
        "",
        "## 원본 가사",
        "",
        song["original_lyrics"],
        "",
        "## 한국어 번역",
        "",
        song["translation_ko"],
        "",
        "## 한국어 발음",
        "",
        song["pronunciation_ko"],
    ]
    if song.get("review_notes"):
        sections.extend(["", "## 수정 메모", "", song["review_notes"]])
    return "\n".join(sections).rstrip() + "\n"


def _song_separate_lyrics_files(song: dict, discord_user_id: str) -> list[discord.File]:
    exports = [
        ("original_lyrics", "original_lyrics", song["original_lyrics"]),
        ("translation_ko", "translation_ko", song["translation_ko"]),
        ("pronunciation_ko", "pronunciation_ko", song["pronunciation_ko"]),
    ]
    files = []
    for part, filename_part, text in exports:
        output_path = _song_lyrics_export_path(
            song["id"],
            song["original_title"],
            discord_user_id,
            part=filename_part,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text.rstrip() + "\n", encoding="utf-8")
        files.append(discord.File(output_path, filename=f"song_{song['id']}_{part}.txt"))
    return files


def _update_song_lyrics(
    *,
    discord_user_id: str,
    song_id: int,
    original_lyrics: str | None,
    translation_ko: str | None,
    pronunciation_ko: str | None,
    review_notes: str | None,
) -> dict:
    updates = {
        "original_lyrics": original_lyrics.strip() if original_lyrics and original_lyrics.strip() else None,
        "translation_ko": translation_ko.strip() if translation_ko and translation_ko.strip() else None,
        "pronunciation_ko": pronunciation_ko.strip() if pronunciation_ko and pronunciation_ko.strip() else None,
        "review_notes": review_notes.strip() if review_notes and review_notes.strip() else None,
    }
    if not any(updates.values()):
        raise ValueError("수정할 가사/번역/발음/메모 중 하나는 입력해야 합니다.")

    with get_connection() as conn:
        existing = conn.execute(
            """
            SELECT l.song_id
            FROM song_lyrics l
            JOIN songs s ON s.id = l.song_id
            WHERE s.discord_user_id = %s AND s.id = %s
            """,
            (discord_user_id, song_id),
        ).fetchone()
        if not existing:
            raise LookupError(f"song #{song_id}를 찾을 수 없습니다.")

        conn.execute(
            """
            UPDATE song_lyrics
            SET
                original_lyrics = COALESCE(%s, original_lyrics),
                translation_ko = COALESCE(%s, translation_ko),
                pronunciation_ko = COALESCE(%s, pronunciation_ko),
                review_notes = COALESCE(%s, review_notes),
                needs_review = FALSE,
                reviewed_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE song_id = %s
            """,
            (
                updates["original_lyrics"],
                updates["translation_ko"],
                updates["pronunciation_ko"],
                updates["review_notes"],
                song_id,
            ),
        )
        conn.commit()

    updated = _get_song_by_id(discord_user_id, song_id)
    if not updated:
        raise LookupError(f"song #{song_id}를 찾을 수 없습니다.")
    return updated


class ScheduleMusicBot(discord.Client):
    """schedule_music 전용 Discord slash command 봇 클라이언트입니다."""

    def __init__(self) -> None:
        """Discord client와 slash command tree를 초기화합니다."""
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        """봇 로그인 직후 DB를 준비하고 slash command를 Discord에 동기화합니다."""
        if settings.database_auto_init:
            init_db()
        if settings.discord_guild_id:
            guild = discord.Object(id=settings.discord_guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            logger.info("Discord 명령어를 길드 %s에 동기화했습니다.", settings.discord_guild_id)
        else:
            await self.tree.sync()
            logger.info("Discord 명령어를 전역으로 동기화했습니다.")


bot = ScheduleMusicBot()


@bot.tree.command(name="artist_add", description="아티스트와 X 계정을 등록합니다.")
@app_commands.describe(
    name="아티스트 이름",
    x_username="@ 포함 여부와 관계없는 X 사용자명",
    display_name="선택 표시 이름",
    notes="선택 메모",
)
async def artist_add(
    interaction: discord.Interaction,
    name: str,
    x_username: str,
    display_name: str | None = None,
    notes: str | None = None,
) -> None:
    """Discord slash command로 아티스트와 X 계정을 등록합니다."""
    await interaction.response.defer(ephemeral=True)
    try:
        artist = _create_artist(str(interaction.user.id), name, x_username, display_name, notes)
    except Exception as exc:
        logger.exception("아티스트 등록 명령 처리에 실패했습니다.")
        await interaction.followup.send(f"아티스트 등록에 실패했습니다: {exc}", ephemeral=True)
        return

    await interaction.followup.send(
        f"아티스트 #{artist['id']} 등록 완료: {artist['name']} (@{_normalize_x_username(x_username)})",
        ephemeral=True,
    )


@bot.tree.command(name="artist_list", description="등록된 아티스트 목록을 보여줍니다.")
async def artist_list(interaction: discord.Interaction) -> None:
    """현재 Discord 사용자가 등록한 아티스트 목록을 보여줍니다."""
    await interaction.response.defer(ephemeral=True)
    artists = _list_artists(str(interaction.user.id))
    if not artists:
        await interaction.followup.send("아직 등록된 아티스트가 없습니다.", ephemeral=True)
        return

    lines = []
    for artist in artists:
        display = artist["display_name"] or artist["name"]
        x_username = artist["x_username"]
        suffix = f" (@{x_username})" if x_username else ""
        lines.append(f"#{artist['id']} {display}{suffix}")

    await interaction.followup.send("\n".join(lines), ephemeral=True)


@bot.tree.command(name="artist_delete", description="ID로 아티스트를 삭제합니다.")
@app_commands.describe(artist_id="/artist_list에 표시된 아티스트 ID")
async def artist_delete(interaction: discord.Interaction, artist_id: int) -> None:
    """현재 Discord 사용자의 아티스트를 ID 기준으로 삭제합니다."""
    await interaction.response.defer(ephemeral=True)
    deleted = _delete_artist(str(interaction.user.id), artist_id)
    if deleted:
        await interaction.followup.send(f"아티스트 #{artist_id}를 삭제했습니다.", ephemeral=True)
    else:
        await interaction.followup.send(f"아티스트 #{artist_id}를 찾을 수 없습니다.", ephemeral=True)


@bot.tree.command(name="source_list", description="라우팅에 사용할 source_id 목록을 보여줍니다.")
async def source_list(interaction: discord.Interaction) -> None:
    """현재 사용자가 등록한 감시 소스 목록을 보여줍니다."""
    await interaction.response.defer(ephemeral=True)
    if not settings.database_url:
        await interaction.followup.send("DATABASE_URL이 설정되어 있어야 조회할 수 있습니다.", ephemeral=True)
        return

    sources = _list_sources_for_user(str(interaction.user.id))
    if not sources:
        await interaction.followup.send("등록된 소스가 없습니다. 먼저 /artist_add로 X 계정을 등록해주세요.", ephemeral=True)
        return

    lines = []
    for source in sources:
        artist = source["display_name"] or source["artist_name"]
        label = f" ({source['label']})" if source["label"] else ""
        active = "" if source["is_active"] else " 비활성"
        lines.append(
            f"#{source['id']} {artist} / `{source['source_type']}` {source['value']}{label}{active}"
        )

    await interaction.followup.send("\n".join(lines), ephemeral=True)


@bot.tree.command(name="route_add", description="소스/글 타입별 Discord 알림 채널을 연결합니다.")
@app_commands.describe(
    item_type="notice, release, live_event, ticket, merch 중 하나",
    channel="알림을 보낼 Discord 채널",
    source_id="/source_list에서 확인한 source_id. 비우면 서버 전체 기본 route로 사용합니다.",
)
@app_commands.choices(
    item_type=[
        app_commands.Choice(name="notice 일반 공지", value="notice"),
        app_commands.Choice(name="release 음원/MV 릴리즈", value="release"),
        app_commands.Choice(name="live_event 라이브/공연", value="live_event"),
        app_commands.Choice(name="ticket 티켓/응모", value="ticket"),
        app_commands.Choice(name="merch 굿즈/상품", value="merch"),
    ]
)
async def route_add(
    interaction: discord.Interaction,
    item_type: str,
    channel: discord.TextChannel,
    source_id: int | None = None,
) -> None:
    """분류된 글 타입을 현재 Discord 서버의 특정 채널로 보내도록 설정합니다."""
    await interaction.response.defer(ephemeral=True)
    try:
        _ensure_manage_guild(interaction)
        guild_id = _guild_id_from_interaction(interaction)
        route = create_notification_route(
            discord_user_id=str(interaction.user.id),
            guild_id=guild_id,
            source_id=source_id,
            item_type=item_type,
            discord_channel_id=str(channel.id),
        )
    except (PermissionError, ValueError, LookupError, NotificationRouteConflictError) as exc:
        await interaction.followup.send(str(exc), ephemeral=True)
        return
    except Exception as exc:
        logger.exception("route_add 명령 처리에 실패했습니다.")
        await interaction.followup.send(f"라우팅 저장에 실패했습니다: {exc}", ephemeral=True)
        return

    await interaction.followup.send(f"라우팅 추가 완료: {_format_route(route)}", ephemeral=True)


@bot.tree.command(name="route_list", description="현재 서버의 Discord 알림 라우팅 목록을 보여줍니다.")
@app_commands.describe(source_id="선택: 특정 source_id만 조회합니다.")
async def route_list(interaction: discord.Interaction, source_id: int | None = None) -> None:
    """현재 서버에 설정된 source/type -> channel 라우팅 목록을 보여줍니다."""
    await interaction.response.defer(ephemeral=True)
    try:
        guild_id = _guild_id_from_interaction(interaction)
        routes = list_notification_routes(guild_id=guild_id, source_id=source_id)
    except ValueError as exc:
        await interaction.followup.send(str(exc), ephemeral=True)
        return
    except Exception as exc:
        logger.exception("route_list 명령 처리에 실패했습니다.")
        await interaction.followup.send(f"라우팅 조회에 실패했습니다: {exc}", ephemeral=True)
        return

    if not routes:
        await interaction.followup.send("등록된 라우팅이 없습니다.", ephemeral=True)
        return

    await interaction.followup.send("\n".join(_format_route(route) for route in routes), ephemeral=True)


@bot.tree.command(name="route_delete", description="route_id로 Discord 알림 라우팅을 삭제합니다.")
@app_commands.describe(route_id="/route_list에 표시된 route id")
async def route_delete(interaction: discord.Interaction, route_id: int) -> None:
    """현재 서버의 라우팅 하나를 삭제합니다."""
    await interaction.response.defer(ephemeral=True)
    try:
        _ensure_manage_guild(interaction)
        guild_id = _guild_id_from_interaction(interaction)
        deleted = delete_notification_route(guild_id=guild_id, route_id=route_id)
    except (PermissionError, ValueError) as exc:
        await interaction.followup.send(str(exc), ephemeral=True)
        return
    except Exception as exc:
        logger.exception("route_delete 명령 처리에 실패했습니다.")
        await interaction.followup.send(f"라우팅 삭제에 실패했습니다: {exc}", ephemeral=True)
        return

    if deleted:
        await interaction.followup.send(f"route #{route_id}를 삭제했습니다.", ephemeral=True)
    else:
        await interaction.followup.send(f"route #{route_id}를 찾을 수 없습니다.", ephemeral=True)


@bot.tree.command(name="route_test", description="설정한 라우팅 채널에 테스트 메시지를 보냅니다.")
@app_commands.describe(route_id="/route_list에 표시된 route id")
async def route_test(interaction: discord.Interaction, route_id: int) -> None:
    """라우팅이 실제 Discord 채널로 전송 가능한지 확인합니다."""
    await interaction.response.defer(ephemeral=True)
    try:
        _ensure_manage_guild(interaction)
        guild_id = _guild_id_from_interaction(interaction)
        route = get_notification_route(guild_id=guild_id, route_id=route_id)
        channel = bot.get_channel(int(route["discord_channel_id"]))
        if channel is None or not hasattr(channel, "send"):
            await interaction.followup.send("채널을 찾을 수 없습니다. 봇 권한과 채널 설정을 확인해주세요.", ephemeral=True)
            return
        await channel.send(f"라우팅 테스트: {_format_route(route)}")
    except (PermissionError, ValueError, NotificationRouteNotFoundError) as exc:
        await interaction.followup.send(str(exc), ephemeral=True)
        return
    except Exception as exc:
        logger.exception("route_test 명령 처리에 실패했습니다.")
        await interaction.followup.send(f"라우팅 테스트에 실패했습니다: {exc}", ephemeral=True)
        return

    await interaction.followup.send("테스트 메시지를 전송했습니다.", ephemeral=True)


@bot.tree.command(name="google_connect", description="Google Calendar를 연결합니다.")
async def google_connect(interaction: discord.Interaction) -> None:
    """현재 Discord 사용자에게 Google Calendar OAuth 연결 링크를 안내합니다."""
    await interaction.response.defer(ephemeral=True)
    if google_connected(str(interaction.user.id)):
        await interaction.followup.send("Google Calendar가 이미 연결되어 있습니다.", ephemeral=True)
        return
    if not google_oauth_configured():
        await interaction.followup.send(
            "서버에 Google OAuth 설정이 아직 없습니다.",
            ephemeral=True,
        )
        return

    auth_url = build_google_auth_url(str(interaction.user.id))
    await interaction.followup.send(
        f"아래 링크에서 Google Calendar를 연결하세요.\n{auth_url}",
        ephemeral=True,
    )


@bot.tree.command(
    name="lyrics_source",
    description="YouTube URL에서 설명란, 상단 댓글, 수동 자막, 오디오 전사 중 하나를 테스트합니다.",
)
@app_commands.describe(
    youtube_url="확인할 YouTube URL",
    source_mode="가사를 가져올 소스입니다. description, comment, caption, audio, manual 중 하나만 사용합니다.",
    lyrics="source_mode가 manual일 때 RawLyrics.text로 사용할 가사입니다.",
    language_code="원문 언어 코드입니다. 예: ja, en, ko",
)
async def lyrics_source(
    interaction: discord.Interaction,
    youtube_url: str,
    source_mode: LyricsSourceMode = "caption",
    lyrics: str | None = None,
    language_code: str = "ja",
) -> None:
    await interaction.response.defer(ephemeral=True)
    caption_client = YouTubeTranscriptCaptionClient()

    try:
        video_id = extract_youtube_video_id(youtube_url)
        try:
            tracks = await caption_client.list_tracks(video_id)
        except YouTubeTranscriptApiException:
            tracks = []

        if source_mode == "manual":
            raw = _raw_lyrics_from_manual_text(
                text=lyrics,
                language_code=language_code,
                source_url=youtube_url,
            )
        else:
            raw = await _collect_raw_lyrics_from_youtube(
                youtube_url=youtube_url,
                language_code=language_code,
                source_mode=source_mode,
            )

        openai_error = None
        try:
            translation_ko, pronunciation_ko = await _transform_caption_preview(raw)
        except Exception as exc:
            logger.exception("가사 미리보기 변환에 실패했습니다.")
            translation_ko, pronunciation_ko = None, None
            openai_error = str(exc)

        report_path = _caption_report_path(video_id, str(interaction.user.id))
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            _caption_report(
                youtube_url=youtube_url,
                tracks=tracks,
                raw=raw,
                translation_ko=translation_ko,
                pronunciation_ko=pronunciation_ko,
            ),
            encoding="utf-8",
        )
    except ValueError as exc:
        await interaction.followup.send(f"올바르지 않은 YouTube URL입니다. {exc}", ephemeral=True)
        return
    except LyricsPipelineError as exc:
        await interaction.followup.send(f"가사 후보를 찾을 수 없습니다. {exc}", ephemeral=True)
        return
    except Exception as exc:
        logger.exception("가사 소스 테스트 명령 처리에 실패했습니다.")
        await interaction.followup.send(f"가사 소스 테스트에 실패했습니다: {exc}", ephemeral=True)
        return

    await interaction.followup.send(
        (
            f"가사 출처: `{raw.source_type}` / 언어: `{raw.language_code or language_code}`\n"
            f"source_mode: `{source_mode}` / 검토 필요: `{raw.needs_review}`\n"
            f"{_openai_status_text(translation_ko, pronunciation_ko, openai_error)}\n"
            f"리포트 저장 경로: `{report_path}`"
        ),
        file=discord.File(report_path),
        ephemeral=True,
    )


@bot.tree.command(name="song_save", description="YouTube 곡 가사, 번역, 발음, Spotify 정보를 DB에 저장합니다.")
@app_commands.describe(
    youtube_url="저장할 곡의 YouTube URL",
    artist="아티스트 이름",
    title="원본 곡 제목",
    title_ko="선택 한글 곡 제목",
    artist_name_ko="선택 한글 아티스트 이름",
    source_mode="가사를 가져올 소스입니다. description, comment, caption, audio, manual 중 하나만 사용합니다.",
    lyrics="source_mode가 manual일 때 RawLyrics.text로 저장할 가사입니다.",
    language_code="원문 언어 코드입니다. 예: ja, en, ko",
)
async def song_save(
    interaction: discord.Interaction,
    youtube_url: str,
    artist: str,
    title: str,
    title_ko: str | None = None,
    artist_name_ko: str | None = None,
    source_mode: LyricsSourceMode = "caption",
    lyrics: str | None = None,
    language_code: str = "ja",
) -> None:
    await interaction.response.defer(ephemeral=True)
    if not settings.database_url:
        await interaction.followup.send("DATABASE_URL이 설정되어 있어야 저장할 수 있습니다.", ephemeral=True)
        return
    if not settings.openai_api_key:
        await interaction.followup.send("OPENAI_API_KEY가 설정되어 있어야 번역/발음을 저장할 수 있습니다.", ephemeral=True)
        return

    try:
        if settings.database_auto_init:
            init_db()

        video_id = extract_youtube_video_id(youtube_url)
        if source_mode == "manual":
            raw = _raw_lyrics_from_manual_text(
                text=lyrics,
                language_code=language_code,
                source_url=youtube_url,
            )
        else:
            raw = await _collect_raw_lyrics_from_youtube(
                youtube_url=youtube_url,
                language_code=language_code,
                source_mode=source_mode,
            )

        ai_client = OpenAiLyricsClient()
        translation_ko, pronunciation_ko = await ai_client.transform_lyrics(
            lyrics=raw.text,
            artist=artist,
            title=title,
        )

        try:
            spotify = await search_spotify_track(artist, title) if spotify_configured() else None
        except Exception:
            logger.exception("Spotify 검색에 실패했습니다. Spotify 정보 없이 곡을 저장합니다.")
            spotify = None
        song_id = _save_song_with_lyrics(
            discord_user_id=str(interaction.user.id),
            youtube_url=youtube_url,
            youtube_video_id=video_id,
            artist_name=artist.strip(),
            original_title=title.strip(),
            title_ko=title_ko.strip() if title_ko else None,
            artist_name_ko=artist_name_ko.strip() if artist_name_ko else None,
            raw=raw,
            translation_ko=translation_ko,
            pronunciation_ko=pronunciation_ko,
            spotify=spotify,
        )
    except ValueError as exc:
        await interaction.followup.send(f"올바르지 않은 YouTube URL입니다. {exc}", ephemeral=True)
        return
    except LyricsPipelineError as exc:
        await interaction.followup.send(f"가사 후보를 찾을 수 없습니다. {exc}", ephemeral=True)
        return
    except Exception as exc:
        logger.exception("곡 저장 명령 처리에 실패했습니다.")
        await interaction.followup.send(f"곡 저장에 실패했습니다: {exc}", ephemeral=True)
        return

    spotify_line = (
        f"Spotify: {spotify.name} - {', '.join(spotify.artists)}"
        if spotify
        else "Spotify: 설정 없음 또는 검색 결과 없음"
    )
    await interaction.followup.send(
        (
            f"곡 저장 완료: song #{song_id}\n"
            f"제목: {title}\n"
            f"아티스트: {artist}\n"
            f"가사 출처: `{raw.source_type}` / 언어: `{raw.language_code or language_code}`\n"
            f"{spotify_line}"
        ),
        ephemeral=True,
    )


@bot.tree.command(name="song_show", description="저장된 곡을 아티스트와 제목으로 조회합니다.")
@app_commands.describe(
    artist="아티스트 이름입니다. 원본 이름과 한글 이름 모두 검색합니다.",
    title="곡 제목입니다. 원본 제목과 한글 제목 모두 검색합니다.",
    include_lyrics="True이면 원본 가사, 번역, 발음을 txt 파일로 함께 받습니다.",
    separate_lyrics="True이면 원본 가사, 번역, 발음을 각각 별도 txt 파일로 받습니다.",
)
async def song_show(
    interaction: discord.Interaction,
    artist: str,
    title: str,
    include_lyrics: bool = False,
    separate_lyrics: bool = False,
) -> None:
    await interaction.response.defer(ephemeral=True)
    if not settings.database_url:
        await interaction.followup.send("DATABASE_URL이 설정되어 있어야 조회할 수 있습니다.", ephemeral=True)
        return

    try:
        songs = _find_songs(str(interaction.user.id), artist, title)
    except Exception as exc:
        logger.exception("곡 조회 명령 처리에 실패했습니다.")
        await interaction.followup.send(f"곡 조회에 실패했습니다: {exc}", ephemeral=True)
        return

    if not songs:
        await interaction.followup.send("검색된 곡이 없습니다. 원본 제목이나 한글 제목으로 다시 시도해주세요.", ephemeral=True)
        return
    if len(songs) > 1:
        await interaction.followup.send(_format_song_candidates(songs), ephemeral=True)
        return

    song = songs[0]
    if include_lyrics:
        if separate_lyrics:
            await interaction.followup.send(
                _format_song_summary(song),
                files=_song_separate_lyrics_files(song, str(interaction.user.id)),
                ephemeral=True,
            )
            return

        output_path = _song_lyrics_export_path(song["id"], song["original_title"], str(interaction.user.id))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(_song_lyrics_export_text(song), encoding="utf-8")
        await interaction.followup.send(
            _format_song_summary(song),
            file=discord.File(output_path),
            ephemeral=True,
        )
        return

    await interaction.followup.send(_format_song_summary(song), ephemeral=True)


@bot.tree.command(name="song_show_by_id", description="저장된 곡을 song id로 정확히 조회합니다.")
@app_commands.describe(
    song_id="/song_save 또는 /song_show에서 확인한 song id입니다.",
    include_lyrics="True이면 원본 가사, 번역, 발음을 txt 파일로 함께 받습니다.",
    separate_lyrics="True이면 원본 가사, 번역, 발음을 각각 별도 txt 파일로 받습니다.",
)
async def song_show_by_id(
    interaction: discord.Interaction,
    song_id: int,
    include_lyrics: bool = False,
    separate_lyrics: bool = False,
) -> None:
    await interaction.response.defer(ephemeral=True)
    if not settings.database_url:
        await interaction.followup.send("DATABASE_URL이 설정되어 있어야 조회할 수 있습니다.", ephemeral=True)
        return

    song = _get_song_by_id(str(interaction.user.id), song_id)
    if not song:
        await interaction.followup.send(f"song #{song_id}를 찾을 수 없습니다.", ephemeral=True)
        return

    if include_lyrics:
        if separate_lyrics:
            await interaction.followup.send(
                _format_song_summary(song),
                files=_song_separate_lyrics_files(song, str(interaction.user.id)),
                ephemeral=True,
            )
            return

        output_path = _song_lyrics_export_path(song["id"], song["original_title"], str(interaction.user.id))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(_song_lyrics_export_text(song), encoding="utf-8")
        await interaction.followup.send(
            _format_song_summary(song),
            file=discord.File(output_path),
            ephemeral=True,
        )
        return

    await interaction.followup.send(_format_song_summary(song), ephemeral=True)


@bot.tree.command(name="song_lyrics_update", description="저장된 곡의 원본 가사, 번역, 한국어 발음을 수정합니다.")
@app_commands.describe(
    song_id="수정할 song id입니다.",
    original_lyrics_file="새 원본 가사가 들어있는 UTF-8 txt 파일입니다.",
    translation_ko_file="새 한국어 번역이 들어있는 UTF-8 txt 파일입니다.",
    pronunciation_ko_file="새 한국어 발음이 들어있는 UTF-8 txt 파일입니다.",
    original_lyrics="짧은 원본 가사는 직접 입력할 수 있습니다.",
    translation_ko="짧은 한국어 번역은 직접 입력할 수 있습니다.",
    pronunciation_ko="짧은 한국어 발음은 직접 입력할 수 있습니다.",
    review_notes="수정 메모입니다.",
)
async def song_lyrics_update(
    interaction: discord.Interaction,
    song_id: int,
    original_lyrics_file: discord.Attachment | None = None,
    translation_ko_file: discord.Attachment | None = None,
    pronunciation_ko_file: discord.Attachment | None = None,
    original_lyrics: str | None = None,
    translation_ko: str | None = None,
    pronunciation_ko: str | None = None,
    review_notes: str | None = None,
) -> None:
    await interaction.response.defer(ephemeral=True)
    if not settings.database_url:
        await interaction.followup.send("DATABASE_URL이 설정되어 있어야 수정할 수 있습니다.", ephemeral=True)
        return

    try:
        original_from_file = await _fetch_text_attachment_text(original_lyrics_file, "원본 가사")
        translation_from_file = await _fetch_text_attachment_text(translation_ko_file, "한국어 번역")
        pronunciation_from_file = await _fetch_text_attachment_text(pronunciation_ko_file, "한국어 발음")
        updated = _update_song_lyrics(
            discord_user_id=str(interaction.user.id),
            song_id=song_id,
            original_lyrics=original_from_file or original_lyrics,
            translation_ko=translation_from_file or translation_ko,
            pronunciation_ko=pronunciation_from_file or pronunciation_ko,
            review_notes=review_notes,
        )
    except LookupError as exc:
        await interaction.followup.send(str(exc), ephemeral=True)
        return
    except ValueError as exc:
        await interaction.followup.send(str(exc), ephemeral=True)
        return
    except Exception as exc:
        logger.exception("곡 가사 수정 명령 처리에 실패했습니다.")
        await interaction.followup.send(f"곡 가사 수정에 실패했습니다: {exc}", ephemeral=True)
        return

    await interaction.followup.send(
        f"song #{updated['id']} 수정 완료\n{updated['artist_name']} - {updated['original_title']}",
        ephemeral=True,
    )


@bot.tree.command(name="namuwiki_template_add", description="나무위키 문서 템플릿을 저장합니다.")
@app_commands.describe(
    template_id="나중에 선택할 템플릿 ID입니다. 예: hachi_song",
    name="템플릿 표시 이름입니다.",
    template_file="나무위키 예시 문서가 들어 있는 UTF-8 txt 파일입니다.",
    template_text="짧은 템플릿이면 직접 입력할 수 있습니다.",
    description="선택 설명입니다.",
)
async def namuwiki_template_add(
    interaction: discord.Interaction,
    template_id: str,
    name: str,
    template_file: discord.Attachment | None = None,
    template_text: str | None = None,
    description: str | None = None,
) -> None:
    await interaction.response.defer(ephemeral=True)
    try:
        template_file_text = await _fetch_template_attachment_text(template_file)
        template_example = _template_text_from_inputs(template_text, template_file_text)
        template = save_template(
            NamuWikiTemplateCreate(
                template_id=template_id.strip(),
                name=name.strip(),
                description=description,
                template_example=template_example,
            )
        )
    except Exception as exc:
        logger.exception("나무위키 템플릿 저장 명령 처리에 실패했습니다.")
        await interaction.followup.send(f"템플릿 저장에 실패했습니다: {exc}", ephemeral=True)
        return

    await interaction.followup.send(
        (
            f"나무위키 템플릿 저장 완료: `{template.template_id}`\n"
            f"이름: {template.name}\n"
            f"길이: {len(template.template_example)}자"
        ),
        ephemeral=True,
    )


@bot.tree.command(name="namuwiki_template_list", description="저장된 나무위키 템플릿 목록을 봅니다.")
async def namuwiki_template_list(interaction: discord.Interaction) -> None:
    await interaction.response.defer(ephemeral=True)
    templates = list_templates()
    if not templates:
        await interaction.followup.send("저장된 나무위키 템플릿이 없습니다.", ephemeral=True)
        return

    lines = []
    for template in templates[:25]:
        suffix = f" - {template.description}" if template.description else ""
        lines.append(f"`{template.template_id}`: {template.name}{suffix}")

    await interaction.followup.send("\n".join(lines), ephemeral=True)


@bot.tree.command(name="namuwiki_render", description="저장된 템플릿으로 나무위키 곡 문서를 만듭니다.")
@app_commands.describe(
    template_id="사용할 저장 템플릿 ID입니다.",
    title="곡 제목입니다.",
    artist="아티스트 이름입니다.",
    youtube_url="가사를 가져올 YouTube URL입니다.",
    release_date="선택 발매일입니다. 예: 2026. 06. 25.",
    album="선택 앨범/싱글명입니다.",
    language_code="원문 언어 코드입니다. 예: ja, en, ko",
    source_mode="가사를 가져올 소스입니다. description, comment, caption, audio, manual 중 하나만 사용합니다.",
    lyrics="source_mode가 manual일 때 RawLyrics.text로 사용할 가사입니다.",
    extra_instruction="템플릿 적용 시 추가 지시입니다.",
)
async def namuwiki_render(
    interaction: discord.Interaction,
    template_id: str,
    title: str,
    artist: str,
    youtube_url: str,
    release_date: str | None = None,
    album: str | None = None,
    cover_file: str | None = None,
    lyricist: str | None = None,
    composer: str | None = None,
    arranger: str | None = None,
    illustrator: str | None = None,
    video_credit: str | None = None,
    producer: str | None = None,
    executive_producer: str | None = None,
    recording_director: str | None = None,
    recording_mixing: str | None = None,
    extra_credits: str | None = None,
    lyrics: str | None = None,
    language_code: str = "ja",
    source_mode: LyricsSourceMode = "caption",
    extra_instruction: str | None = None,
) -> None:
    await interaction.response.defer(ephemeral=True)
    if not settings.openai_api_key:
        await interaction.followup.send("OPENAI_API_KEY가 설정되어 있어야 합니다.", ephemeral=True)
        return

    try:
        template = get_template(template_id.strip())
        raw = await _collect_raw_lyrics_for_namuwiki(
            youtube_url=youtube_url,
            language_code=language_code,
            source_mode=source_mode,
            manual_lyrics=lyrics,
        )

        ai_client = OpenAiLyricsClient()
        translation_ko, pronunciation_ko = await ai_client.transform_lyrics(
            lyrics=raw.text,
            artist=artist,
            title=title,
        )
        song = NamuWikiSongArticleRequest(
            title=title,
            artist=artist,
            release_date=release_date,
            album=album,
            cover_file=cover_file,
            lyricist=lyricist,
            composer=composer,
            arranger=arranger,
            illustrator=illustrator,
            video=video_credit,
            producer=producer,
            executive_producer=executive_producer,
            recording_director=recording_director,
            recording_mixing=recording_mixing,
            extra_credits=_parse_namuwiki_extra_credits(extra_credits),
            youtube_url=youtube_url,
            lyrics=_build_lyric_lines(raw.text, pronunciation_ko, translation_ko),
        )
        article = await render_song_article_from_template(
            NamuWikiTemplateSongArticleRequest(
                template_example=template.template_example,
                song=song,
                extra_instruction=extra_instruction,
            )
        )

        output_path = _namuwiki_article_path(title, str(interaction.user.id))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(article, encoding="utf-8")
    except NamuWikiTemplateNotFoundError:
        await interaction.followup.send(f"템플릿 `{template_id}`를 찾을 수 없습니다.", ephemeral=True)
        return
    except (ValueError, LyricsPipelineError, NamuWikiAiRenderError) as exc:
        await interaction.followup.send(f"나무위키 문서 생성에 실패했습니다: {exc}", ephemeral=True)
        return
    except Exception as exc:
        logger.exception("나무위키 문서 생성 명령 처리에 실패했습니다.")
        await interaction.followup.send(f"나무위키 문서 생성에 실패했습니다: {exc}", ephemeral=True)
        return

    await interaction.followup.send(
        (
            f"나무위키 문서 생성 완료: `{title}`\n"
            f"템플릿 `{template.template_id}` / source_mode: `{source_mode}` / 가사 출처: `{raw.source_type}`\n"
            f"검토 필요: `{raw.needs_review}` / 저장 경로: `{output_path}`"
        ),
        file=discord.File(output_path),
        ephemeral=True,
    )


async def start_discord_bot() -> None:
    """토큰이 설정되어 있으면 Discord 봇을 시작하고, 없으면 비활성 상태로 둡니다."""
    if not settings.discord_bot_token:
        logger.warning("DISCORD_BOT_TOKEN이 설정되어 있지 않아 Discord 봇을 비활성화합니다.")
        return

    await bot.start(settings.discord_bot_token)
