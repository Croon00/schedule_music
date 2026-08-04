from __future__ import annotations

import logging
import re
from typing import Any

from psycopg.types.json import Jsonb

from app.core.config import settings
from app.core.db import get_connection
from app.integrations.youtube_context import fetch_setlist_comment, fetch_video_metadata
from app.integrations.karaoke_lookup import lookup_karaoke_numbers, split_song_credit
from app.lyrics_pipeline.youtube import canonical_youtube_watch_url, extract_youtube_video_id


logger = logging.getLogger(__name__)
TIMESTAMP_LINE_RE = re.compile(
    r"^\s*(?P<timestamp>(?:\d{1,2}:)?\d{1,2}:\d{2})"
    r"(?:\s*[-–—|｜:：]\s*|\s+)"
    r"(?P<title>.+?)\s*$"
)
MAX_ARCHIVE_ATTEMPTS = 168


def register_youtube_live(
    *,
    source_item_id: int,
    source_id: int,
    youtube_video_id: str,
    youtube_url: str,
) -> None:
    """Register a YouTube live so its post-stream setlist can be collected."""
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO youtube_live_archives (
                source_item_id, source_id, youtube_video_id, youtube_url
            )
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (source_item_id, youtube_video_id) DO NOTHING
            """,
            (source_item_id, source_id, youtube_video_id, youtube_url),
        )
        conn.commit()


async def add_youtube_live_url(youtube_url: str, artist_name: str | None = None) -> int:
    """Register a URL directly and immediately collect its dated setlist."""
    video_id = extract_youtube_video_id(youtube_url)
    canonical_url = canonical_youtube_watch_url(youtube_url)
    metadata = await fetch_video_metadata(video_id)
    context = await fetch_setlist_comment(video_id)
    comment = context.text if context else None
    setlist = parse_setlist_comment(comment or "")

    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM youtube_live_archives WHERE youtube_video_id = %s ORDER BY id LIMIT 1",
            (video_id,),
        ).fetchone()
        values = (
            canonical_url,
            artist_name.strip() if artist_name else None,
            metadata.title if metadata else None,
            metadata.published_at if metadata else None,
            metadata.broadcast_at if metadata else None,
            "ready" if setlist else "pending",
            comment,
            Jsonb(setlist),
        )
        if existing:
            conn.execute(
                """
                UPDATE youtube_live_archives SET youtube_url = %s,
                    performer_name = COALESCE(%s, performer_name),
                    video_title = COALESCE(%s, video_title),
                    published_at = COALESCE(%s, published_at),
                    broadcast_at = COALESCE(%s, broadcast_at), status = %s,
                    top_comment = COALESCE(%s, top_comment), setlist = %s,
                    attempts = attempts + 1, last_checked_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (*values, existing["id"]),
            )
            archive_id = existing["id"]
        else:
            row = conn.execute(
                """
                INSERT INTO youtube_live_archives (
                    youtube_video_id, youtube_url, performer_name, video_title, published_at,
                    broadcast_at, status, top_comment, setlist, attempts,
                    last_checked_at, next_check_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 1,
                          CURRENT_TIMESTAMP, CURRENT_TIMESTAMP + INTERVAL '1 hour')
                RETURNING id
                """,
                (video_id, *values),
            ).fetchone()
            archive_id = row["id"]
        conn.commit()
    _replace_song_performances(archive_id, setlist)
    await _enrich_karaoke_numbers(archive_id)
    return int(archive_id)


def parse_setlist_comment(text: str) -> list[dict[str, str]]:
    """Extract timestamp/song pairs from a YouTube top comment."""
    entries: list[dict[str, str]] = []
    for line in text.splitlines():
        match = TIMESTAMP_LINE_RE.match(line)
        if not match:
            continue
        entries.append(
            {
                "timestamp": match.group("timestamp"),
                "title": match.group("title").strip(),
            }
        )
    return entries


async def refresh_pending_youtube_lives(limit: int = 10) -> int:
    """Check due YouTube lives and store a timestamped top-comment setlist."""
    if not settings.youtube_api_key:
        return 0

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, youtube_video_id
            FROM youtube_live_archives
            WHERE status = 'pending'
                AND attempts < %s
                AND next_check_at <= CURRENT_TIMESTAMP
            ORDER BY next_check_at, id
            LIMIT %s
            """,
            (MAX_ARCHIVE_ATTEMPTS, limit),
        ).fetchall()

    updated = 0
    for row in rows:
        try:
            metadata = await fetch_video_metadata(row["youtube_video_id"])
            context = await fetch_setlist_comment(row["youtube_video_id"])
            comment = context.text if context else None
            setlist = parse_setlist_comment(comment or "")
            _save_check_result(
                archive_id=row["id"],
                comment=comment,
                setlist=setlist,
                metadata=metadata,
            )
            if setlist:
                await _enrich_karaoke_numbers(row["id"])
                updated += 1
        except Exception:
            logger.exception(
                "YouTube live archive #%s comment check failed.",
                row["id"],
            )
            _save_check_result(
                archive_id=row["id"],
                comment=None,
                setlist=[],
                metadata=None,
            )
    return updated


def _save_check_result(
    *,
    archive_id: int,
    comment: str | None,
    setlist: list[dict[str, str]],
    metadata: Any | None,
) -> None:
    status = "ready" if setlist else "pending"
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE youtube_live_archives
            SET
                status = %s,
                top_comment = COALESCE(%s, top_comment),
                setlist = %s,
                video_title = COALESCE(%s, video_title),
                published_at = COALESCE(%s, published_at),
                broadcast_at = COALESCE(%s, broadcast_at),
                attempts = attempts + 1,
                last_checked_at = CURRENT_TIMESTAMP,
                next_check_at = CURRENT_TIMESTAMP + INTERVAL '1 hour',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (
                status, comment, Jsonb(setlist),
                metadata.title if metadata else None,
                metadata.published_at if metadata else None,
                metadata.broadcast_at if metadata else None,
                archive_id,
            ),
        )
        conn.commit()
    if setlist:
        _replace_song_performances(archive_id, setlist)


def _timestamp_to_seconds(timestamp: str) -> int:
    parts = [int(part) for part in timestamp.split(":")]
    total = 0
    for part in parts:
        total = total * 60 + part
    return total


def _replace_song_performances(
    archive_id: int,
    setlist: list[dict[str, str]],
) -> None:
    """Store searchable per-song rows using the stream date in Japan time."""
    with get_connection() as conn:
        performed_on = conn.execute(
            """
            SELECT COALESCE(broadcast_at, published_at) AT TIME ZONE 'Asia/Tokyo' AS local_at
            FROM youtube_live_archives WHERE id = %s
            """,
            (archive_id,),
        ).fetchone()["local_at"]
        if performed_on is None:
            return
        conn.execute(
            "DELETE FROM youtube_song_performances WHERE archive_id = %s",
            (archive_id,),
        )
        with conn.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO youtube_song_performances (
                    archive_id, performed_on, start_seconds, timestamp_text, song_title
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                [
                    (
                        archive_id,
                        performed_on.date(),
                        _timestamp_to_seconds(entry["timestamp"]),
                        entry["timestamp"],
                        split_song_credit(entry["title"])[0],
                    )
                    for entry in setlist
                ],
            )
        conn.commit()


async def _enrich_karaoke_numbers(archive_id: int) -> None:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, song_title, original_artist FROM youtube_song_performances
            WHERE archive_id = %s ORDER BY start_seconds, id
            """,
            (archive_id,),
        ).fetchall()
    if not rows:
        return
    # Recover artist credits from the raw setlist when available.
    with get_connection() as conn:
        raw_setlist = conn.execute(
            "SELECT setlist FROM youtube_live_archives WHERE id = %s", (archive_id,)
        ).fetchone()["setlist"]
    songs = [split_song_credit(entry["title"]) for entry in raw_setlist]
    matches = await lookup_karaoke_numbers(songs)
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.executemany(
                """
                UPDATE youtube_song_performances SET original_artist = %s,
                    tj_number = %s, ky_number = %s, karaoke_checked_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                [
                    (match.original_artist, match.tj_number, match.ky_number, row["id"])
                    for row, match in zip(rows, matches, strict=False)
                ],
            )
        conn.commit()


def list_youtube_live_archives(limit: int = 20, artist_name: str | None = None) -> list[dict[str, Any]]:
    """Return recent YouTube live archives with artist and X-post context."""
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT
                y.id,
                y.youtube_url,
                y.status,
                y.setlist,
                y.video_title,
                y.published_at,
                y.broadcast_at,
                y.last_checked_at,
                COALESCE(a.name, y.performer_name, y.video_title, 'YouTube') AS artist_name,
                si.url AS x_post_url
            FROM youtube_live_archives y
            LEFT JOIN artist_sources s ON s.id = y.source_id
            LEFT JOIN artists a ON a.id = s.artist_id
            LEFT JOIN source_items si ON si.id = y.source_item_id
            WHERE (%s IS NULL OR COALESCE(a.name, y.performer_name, '') ILIKE '%%' || %s || '%%')
            ORDER BY COALESCE(y.broadcast_at, y.published_at) DESC NULLS LAST, y.id DESC
            LIMIT %s
            """,
            (artist_name, artist_name, limit),
        ).fetchall()


def get_youtube_live_archive(archive_id: int) -> dict[str, Any] | None:
    """Return one archived live and its parsed setlist."""
    with get_connection() as conn:
        archive = conn.execute(
            """
            SELECT
                y.*,
                COALESCE(a.name, y.performer_name, y.video_title, 'YouTube') AS artist_name,
                si.url AS x_post_url
            FROM youtube_live_archives y
            LEFT JOIN artist_sources s ON s.id = y.source_id
            LEFT JOIN artists a ON a.id = s.artist_id
            LEFT JOIN source_items si ON si.id = y.source_item_id
            WHERE y.id = %s
            """,
            (archive_id,),
        ).fetchone()
        if archive is None:
            return None
        archive["performances"] = conn.execute(
            """
            SELECT id, performed_on, start_seconds, timestamp_text, song_title,
                   original_artist, tj_number, ky_number, karaoke_checked_at
            FROM youtube_song_performances WHERE archive_id = %s
            ORDER BY start_seconds, id
            """,
            (archive_id,),
        ).fetchall()
        return archive
