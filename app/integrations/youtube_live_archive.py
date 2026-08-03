from __future__ import annotations

import logging
import re
from typing import Any

from psycopg.types.json import Jsonb

from app.core.config import settings
from app.core.db import get_connection
from app.integrations.youtube_context import fetch_top_comment


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
            context = await fetch_top_comment(row["youtube_video_id"])
            comment = context.text if context else None
            setlist = parse_setlist_comment(comment or "")
            _save_check_result(
                archive_id=row["id"],
                comment=comment,
                setlist=setlist,
            )
            if setlist:
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
            )
    return updated


def _save_check_result(
    *,
    archive_id: int,
    comment: str | None,
    setlist: list[dict[str, str]],
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
                attempts = attempts + 1,
                last_checked_at = CURRENT_TIMESTAMP,
                next_check_at = CURRENT_TIMESTAMP + INTERVAL '1 hour',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (status, comment, Jsonb(setlist), archive_id),
        )
        conn.commit()


def list_youtube_live_archives(limit: int = 20) -> list[dict[str, Any]]:
    """Return recent YouTube live archives with artist and X-post context."""
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT
                y.id,
                y.youtube_url,
                y.status,
                y.setlist,
                y.last_checked_at,
                a.name AS artist_name,
                si.url AS x_post_url
            FROM youtube_live_archives y
            JOIN artist_sources s ON s.id = y.source_id
            JOIN artists a ON a.id = s.artist_id
            JOIN source_items si ON si.id = y.source_item_id
            ORDER BY y.created_at DESC
            LIMIT %s
            """,
            (limit,),
        ).fetchall()


def get_youtube_live_archive(archive_id: int) -> dict[str, Any] | None:
    """Return one archived live and its parsed setlist."""
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT
                y.*,
                a.name AS artist_name,
                si.url AS x_post_url
            FROM youtube_live_archives y
            JOIN artist_sources s ON s.id = y.source_id
            JOIN artists a ON a.id = s.artist_id
            JOIN source_items si ON si.id = y.source_item_id
            WHERE y.id = %s
            """,
            (archive_id,),
        ).fetchone()
