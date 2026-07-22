from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from psycopg import errors

from app.core.config import settings
from app.core.db import get_connection, init_db
from app.agents.music_graph import run_music_item_graph
from app.integrations.google_calendar import create_calendar_events, google_connected
from app.integrations.notifications import (
    find_notification_routes_for_item,
    update_source_item_classification,
)
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
        "posts_classified": 0,
        "events_created": 0,
        "calendar_events_created": 0,
        "notifications_sent": 0,
        "notifications_skipped": 0,
    }
    if not rows or not x_configured():
        return result

    for source in rows:
        try:
            source_result = await _process_x_source(source)
            for key, value in source_result.items():
                result[key] += value
        except Exception:
            logger.exception("출처 %s 처리 중 agent가 실패했습니다.", source["id"])

    return result


async def _process_x_source(source: dict[str, Any]) -> dict[str, int]:
    """아티스트의 X 계정 하나를 처리해서 새 게시물을 읽고 일정으로 변환합니다."""
    x_username = source["x_username"]
    x_user_id = source["external_user_id"] or await get_x_user_id(x_username)
    if not source["external_user_id"]:
        _update_source_x_user_id(source["id"], x_user_id)

    posts = await fetch_recent_posts(x_user_id, source["last_seen_external_id"])
    posts = sorted(posts, key=lambda post: int(post["id"]))
    result = {
        "posts_seen": len(posts),
        "posts_classified": 0,
        "events_created": 0,
        "calendar_events_created": 0,
        "notifications_sent": 0,
        "notifications_skipped": 0,
    }

    newest_post_id = source["last_seen_external_id"]
    for post in posts:
        newest_post_id = post["id"]
        source_item_id = _insert_source_item(source, post)
        if source_item_id is None:
            continue

        page_context = await _fetch_post_page_context(post)
        raw_text = _combine_raw_text(post["text"], page_context)
        graph_state = await run_music_item_graph(
            source=source,
            post=post,
            page_context=page_context,
            raw_text=raw_text,
        )
        item_type = graph_state["item_type"]
        update_source_item_classification(
            source_item_id=source_item_id,
            item_type=item_type,
            confidence=graph_state.get("classification_confidence"),
        )
        result["posts_classified"] += 1

        event = None
        extracted = graph_state.get("event_extraction")
        if extracted:
            _normalize_ticket_open_from_post(post, extracted)
            _normalize_live_date_from_post(post, extracted)

            event = _insert_event_candidate(source, post, extracted, raw_text)
            result["events_created"] += 1

        if event and google_connected(source["discord_user_id"]):
            provider_events = await create_calendar_events(source["discord_user_id"], event)
            for event_type, provider_event_id in provider_events.items():
                _insert_calendar_sync(
                    source["discord_user_id"],
                    event["id"],
                    provider_event_id,
                    event_type,
                )
                result["calendar_events_created"] += 1

        notification_result = await _notify_discord_routes(
            source=source,
            post=post,
            item_type=item_type,
            classification_reason=graph_state.get("classification_reason"),
            event=event,
        )
        result["notifications_sent"] += notification_result["sent"]
        result["notifications_skipped"] += notification_result["skipped"]

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


def _insert_source_item(source: dict[str, Any], post: dict[str, Any]) -> int | None:
    """X 게시물을 source_items에 저장하고 새 row id를 반환합니다.

    이미 저장된 게시물이면 None을 반환합니다. 반환된 row id는 분류 결과를
    같은 source_items row에 업데이트하는 데 사용합니다.
    """
    published_at = _parse_datetime(post.get("created_at"))
    with get_connection() as conn:
        try:
            cursor = conn.execute(
                """
                INSERT INTO source_items (
                    discord_user_id, source_id, external_id, url, published_at, raw_text
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
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
            source_item_id = cursor.fetchone()["id"]
            conn.commit()
            return int(source_item_id)
        except errors.UniqueViolation:
            conn.rollback()
            return None


def _insert_event_candidate(
    source: dict[str, Any],
    post: dict[str, Any],
    extracted: dict[str, Any],
    raw_text: str,
) -> dict[str, Any]:
    """AI가 추출한 공연/예매 정보를 일정 후보 테이블에 저장합니다."""
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
    """Google Calendar에 생성한 event ID를 저장해 중복 등록을 추적합니다."""
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


async def _notify_discord_routes(
    *,
    source: dict[str, Any],
    post: dict[str, Any],
    item_type: str,
    classification_reason: str | None,
    event: dict[str, Any] | None,
) -> dict[str, int]:
    """Send a classified item to every active Discord route for this source/type.

    The agent can also be run from a CLI or tests without a logged-in Discord bot.
    In that case this function skips delivery instead of waiting forever.
    """
    routes = find_notification_routes_for_item(source_id=source["id"], item_type=item_type)
    if not routes:
        return {"sent": 0, "skipped": 0}

    try:
        from app.bots.discord_bot import bot
    except Exception:
        logger.exception("Discord bot import failed while sending notifications.")
        return {"sent": 0, "skipped": len(routes)}

    if bot.is_closed() or not bot.is_ready():
        logger.info("Discord bot is not ready; skipped %s route notifications.", len(routes))
        return {"sent": 0, "skipped": len(routes)}

    message = _build_notification_message(
        source=source,
        post=post,
        item_type=item_type,
        classification_reason=classification_reason,
        event=event,
    )
    sent = 0
    skipped = 0
    for route in routes:
        channel = bot.get_channel(int(route["discord_channel_id"]))
        if channel is None or not hasattr(channel, "send"):
            skipped += 1
            continue
        try:
            await channel.send(message)
            sent += 1
        except Exception:
            skipped += 1
            logger.exception("Discord route %s notification failed.", route["id"])
    return {"sent": sent, "skipped": skipped}


def _build_notification_message(
    *,
    source: dict[str, Any],
    post: dict[str, Any],
    item_type: str,
    classification_reason: str | None,
    event: dict[str, Any] | None,
) -> str:
    """Build a short Discord message for one classified source item."""
    labels = {
        "notice": "공지",
        "release": "릴리즈",
        "live_event": "라이브",
        "ticket": "티켓",
        "merch": "굿즈",
        "irrelevant": "무시",
    }
    title = event["title"] if event and event.get("title") else _first_line(post.get("text", "새 글"))
    url = post_url(source["x_username"], post["id"])
    lines = [
        f"[{labels.get(item_type, item_type)}] {source['artist_name']}",
        title,
    ]

    if event:
        if event.get("starts_at"):
            lines.append(f"일정: {event['starts_at']}")
        if event.get("venue"):
            lines.append(f"장소: {event['venue']}")
        if event.get("ticket_opens_at"):
            lines.append(f"티켓 시작: {event['ticket_opens_at']}")
        if event.get("ticket_closes_at"):
            lines.append(f"티켓 마감: {event['ticket_closes_at']}")
        if event.get("ticket_url"):
            lines.append(f"티켓 링크: {event['ticket_url']}")

    excerpt = _truncate_text(post.get("text", ""), 600)
    if excerpt and excerpt != title:
        lines.extend(["", excerpt])
    if item_type == "irrelevant":
        lines.extend(["", "(분류 : 잡담)"])
    elif classification_reason:
        lines.extend(["", f"분류: `{item_type}` ({classification_reason})"])
    lines.append(f"원문: {url}")

    message = "\n".join(line for line in lines if line is not None)
    return _truncate_text(message, 1900)


def _first_line(value: str) -> str:
    """Return the first non-empty line for compact notification titles."""
    for line in value.splitlines():
        stripped = line.strip()
        if stripped:
            return _truncate_text(stripped, 160)
    return "새 글"


def _truncate_text(value: str, max_chars: int) -> str:
    """Keep Discord messages safely under the 2000 character limit."""
    stripped = value.strip()
    if len(stripped) <= max_chars:
        return stripped
    return stripped[: max_chars - 1].rstrip() + "…"


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
    """Railway 프로세스가 살아 있는 동안 설정된 주기마다 agent를 반복 실행합니다."""
    if not settings.agent_run_on_start:
        await asyncio.sleep(settings.agent_interval_seconds)

    while True:
        try:
            result = await run_agent_once()
            logger.info("agent 실행 완료: %s", result)
        except Exception:
            logger.exception("agent 실행에 실패했습니다.")

        await asyncio.sleep(settings.agent_interval_seconds)
