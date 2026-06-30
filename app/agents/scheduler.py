from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from psycopg import errors

from app.core.config import settings
from app.core.db import get_connection, init_db
from app.integrations.ai_extractor import extract_music_event, openai_configured
from app.integrations.google_calendar import create_calendar_events, google_connected
from app.integrations.web_pages import fetch_public_page_text
from app.integrations.x_client import fetch_recent_posts, get_x_user_id, post_url, x_configured

logger = logging.getLogger(__name__)
JST = timezone(timedelta(hours=9))


async def run_agent_once() -> dict[str, int]:
    """등록된 X 출처를 한 번 순회하며 새 게시물, 일정 후보, 캘린더 등록을 처리합니다."""
    if settings.database_auto_init:
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
            logger.exception("출처 %s 처리 중 에이전트가 실패했습니다.", source["id"])

    return result


async def _process_x_source(source: dict[str, Any]) -> dict[str, int]:
    """아티스트의 X 계정 하나를 처리해서 새 게시물을 읽고 일정으로 변환합니다."""
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

        page_context = await _fetch_post_page_context(post)
        raw_text = _combine_raw_text(post["text"], page_context)
        extracted = await extract_music_event(source["artist_name"], post["text"], page_context)
        if not extracted:
            continue
        _normalize_ticket_open_from_post(post, extracted)
        _normalize_live_date_from_post(post, extracted)

        event = _insert_event_candidate(source, post, extracted, raw_text)
        result["events_created"] += 1

        if google_connected(source["discord_user_id"]):
            provider_events = await create_calendar_events(source["discord_user_id"], event)
            for event_type, provider_event_id in provider_events.items():
                _insert_calendar_sync(
                    source["discord_user_id"],
                    event["id"],
                    provider_event_id,
                    event_type,
                )
                result["calendar_events_created"] += 1

    if newest_post_id:
        _update_last_seen(source["id"], newest_post_id)

    return result


def _update_source_x_user_id(source_id: int, x_user_id: str) -> None:
    """X username으로 조회한 X 내부 user id를 source row에 저장합니다."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE artist_sources SET external_user_id = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (x_user_id, source_id),
        )
        conn.commit()


def _update_last_seen(source_id: int, post_id: str) -> None:
    """다음 agent 실행 때 중복으로 읽지 않도록 마지막으로 본 X 게시물 ID를 저장합니다."""
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
    """X 게시물 원문을 source_items에 저장하고, 이미 저장된 게시물이면 False를 반환합니다."""
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
    raw_text: str,
) -> dict[str, Any]:
    """AI가 추출한 공연/티켓 정보를 일정 후보 테이블에 저장합니다."""
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO event_candidates (
                artist_id, discord_user_id, source_id, title, starts_at, venue,
                ticket_opens_at, ticket_closes_at, ticket_url, price_text,
                source_url, raw_text, status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'ready')
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
                extracted.get("ticket_closes_at"),
                extracted.get("ticket_url"),
                extracted.get("price_text"),
                post_url(source["x_username"], post["id"]),
                raw_text,
            ),
        )
        event = cursor.fetchone()
        conn.commit()
        return event


def _insert_calendar_sync(
    discord_user_id: str,
    event_candidate_id: int,
    provider_event_id: str,
    event_type: str = "live",
) -> None:
    """Google Calendar에 생성된 이벤트 ID를 저장해 중복 등록을 추적합니다."""
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO calendar_syncs (
                discord_user_id, event_candidate_id, provider_event_id, event_type
            )
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (discord_user_id, event_candidate_id, provider, event_type) DO NOTHING
            """,
            (discord_user_id, event_candidate_id, provider_event_id, event_type),
        )
        conn.commit()


async def _fetch_post_page_context(post: dict[str, Any]) -> str | None:
    urls = _extract_post_urls(post)
    if not urls:
        return None

    chunks = []
    for url in urls[:3]:
        text = await fetch_public_page_text(url)
        if text:
            chunks.append(f"URL: {url}\n{text}")
    return "\n\n".join(chunks) if chunks else None


def _extract_post_urls(post: dict[str, Any]) -> list[str]:
    urls = []
    for item in (post.get("entities") or {}).get("urls") or []:
        url = item.get("expanded_url") or item.get("unwound_url") or item.get("url")
        if url and url not in urls:
            urls.append(url)
    return urls


def _combine_raw_text(post_text: str, page_context: str | None) -> str:
    if not page_context:
        return post_text
    return f"{post_text}\n\n--- Linked page context ---\n{page_context}"


def _normalize_ticket_open_from_post(post: dict[str, Any], extracted: dict[str, Any]) -> None:
    """Use the post timestamp when a ticket-start announcement lacks a clear date."""
    ticket_opens_at = extracted.get("ticket_opens_at")
    published_at = _parse_datetime(post.get("created_at"))
    if not ticket_opens_at or not published_at:
        return

    parsed_ticket_opens_at = _parse_datetime(ticket_opens_at)
    if parsed_ticket_opens_at and parsed_ticket_opens_at.tzinfo is None:
        parsed_ticket_opens_at = parsed_ticket_opens_at.replace(tzinfo=timezone.utc)
    if parsed_ticket_opens_at and parsed_ticket_opens_at < published_at:
        extracted["ticket_opens_at"] = published_at.astimezone(JST).isoformat()


def _normalize_live_date_from_post(post: dict[str, Any], extracted: dict[str, Any]) -> None:
    """Infer the first live date from compact Japanese M.D date notation."""
    if extracted.get("starts_at") or not extracted.get("is_live_event"):
        return

    published_at = _parse_datetime(post.get("created_at"))
    if not published_at:
        return

    match = re.search(r"(?<!\d)(1[0-2]|0?[1-9])\.(3[01]|[12]\d|0?[1-9])(?!\d)", post.get("text", ""))
    if not match:
        return

    month = int(match.group(1))
    day = int(match.group(2))
    local_published = published_at.astimezone(JST)
    year = local_published.year
    if (month, day) < (local_published.month, local_published.day):
        year += 1

    extracted["starts_at"] = f"{year:04d}-{month:02d}-{day:02d}"


def _parse_datetime(value: str | None) -> datetime | None:
    """X API의 ISO 문자열 시간을 Python datetime으로 변환합니다."""
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def agent_loop() -> None:
    """Railway 프로세스가 살아있는 동안 설정된 주기마다 agent를 반복 실행합니다."""
    if not settings.agent_run_on_start:
        await asyncio.sleep(settings.agent_interval_seconds)

    while True:
        try:
            result = await run_agent_once()
            logger.info("에이전트 실행 완료: %s", result)
        except Exception:
            logger.exception("에이전트 실행에 실패했습니다.")

        await asyncio.sleep(settings.agent_interval_seconds)
