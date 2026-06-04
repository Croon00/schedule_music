from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from psycopg import errors

from app.core.config import settings
from app.core.db import get_connection, init_db
from app.integrations.ai_extractor import extract_music_event, openai_configured
from app.integrations.google_calendar import create_calendar_event, google_connected
from app.integrations.x_client import fetch_recent_posts, get_x_user_id, post_url, x_configured

logger = logging.getLogger(__name__)


async def run_agent_once() -> dict[str, int]:
    init_db()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                s.id,
                s.artist_id,
                s.value AS x_username,
                s.external_user_id,
                s.last_seen_external_id,
                a.name AS artist_name,
                a.discord_user_id
            FROM artist_sources s
            JOIN artists a ON a.id = s.artist_id
            WHERE s.is_active = TRUE
                AND s.source_type = 'x'
                AND a.discord_user_id IS NOT NULL
            ORDER BY s.id
            """
        ).fetchall()

    result = {
        "active_x_sources": len(rows),
        "posts_seen": 0,
        "events_created": 0,
        "calendar_events_created": 0,
    }
    if not rows or not x_configured() or not openai_configured():
        return result

    for source in rows:
        try:
            source_result = await _process_x_source(source)
            for key, value in source_result.items():
                result[key] += value
        except Exception:
            logger.exception("agent failed for source %s", source["id"])

    return result


async def _process_x_source(source: dict[str, Any]) -> dict[str, int]:
    x_username = source["x_username"]
    x_user_id = source["external_user_id"] or await get_x_user_id(x_username)
    if not source["external_user_id"]:
        _update_source_x_user_id(source["id"], x_user_id)

    posts = await fetch_recent_posts(x_user_id, source["last_seen_external_id"])
    posts = sorted(posts, key=lambda post: int(post["id"]))
    result = {"posts_seen": len(posts), "events_created": 0, "calendar_events_created": 0}

    newest_post_id = source["last_seen_external_id"]
    for post in posts:
        newest_post_id = post["id"]
        inserted = _insert_source_item(source, post)
        if not inserted:
            continue

        extracted = await extract_music_event(source["artist_name"], post["text"])
        if not extracted:
            continue

        event = _insert_event_candidate(source, post, extracted)
        result["events_created"] += 1

        if google_connected(source["discord_user_id"]):
            provider_event_id = await create_calendar_event(source["discord_user_id"], event)
            _insert_calendar_sync(source["discord_user_id"], event["id"], provider_event_id)
            result["calendar_events_created"] += 1

    if newest_post_id:
        _update_last_seen(source["id"], newest_post_id)

    return result


def _update_source_x_user_id(source_id: int, x_user_id: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE artist_sources SET external_user_id = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (x_user_id, source_id),
        )
        conn.commit()


def _update_last_seen(source_id: int, post_id: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE artist_sources
            SET last_seen_external_id = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (post_id, source_id),
        )
        conn.commit()


def _insert_source_item(source: dict[str, Any], post: dict[str, Any]) -> bool:
    published_at = _parse_datetime(post.get("created_at"))
    with get_connection() as conn:
        try:
            conn.execute(
                """
                INSERT INTO source_items (
                    discord_user_id, source_id, external_id, url, published_at, raw_text
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    source["discord_user_id"],
                    source["id"],
                    post["id"],
                    post_url(source["x_username"], post["id"]),
                    published_at,
                    post["text"],
                ),
            )
            conn.commit()
            return True
        except errors.UniqueViolation:
            conn.rollback()
            return False


def _insert_event_candidate(
    source: dict[str, Any],
    post: dict[str, Any],
    extracted: dict[str, Any],
) -> dict[str, Any]:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO event_candidates (
                artist_id, discord_user_id, source_id, title, starts_at, venue,
                ticket_opens_at, ticket_url, price_text, source_url, raw_text, status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'ready')
            RETURNING *
            """,
            (
                source["artist_id"],
                source["discord_user_id"],
                source["id"],
                extracted["title"],
                extracted.get("starts_at"),
                extracted.get("venue"),
                extracted.get("ticket_opens_at"),
                extracted.get("ticket_url"),
                extracted.get("price_text"),
                post_url(source["x_username"], post["id"]),
                post["text"],
            ),
        )
        event = cursor.fetchone()
        conn.commit()
        return event


def _insert_calendar_sync(discord_user_id: str, event_candidate_id: int, provider_event_id: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO calendar_syncs (discord_user_id, event_candidate_id, provider_event_id)
            VALUES (%s, %s, %s)
            ON CONFLICT (discord_user_id, event_candidate_id, provider) DO NOTHING
            """,
            (discord_user_id, event_candidate_id, provider_event_id),
        )
        conn.commit()


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def agent_loop() -> None:
    while True:
        try:
            result = await run_agent_once()
            logger.info("agent run completed: %s", result)
        except Exception:
            logger.exception("agent run failed")

        await asyncio.sleep(settings.agent_interval_seconds)
