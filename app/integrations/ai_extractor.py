from __future__ import annotations

import json
from typing import Any

from openai import AsyncOpenAI

from app.core.config import settings


EVENT_SCHEMA = {
    "name": "music_event_extraction",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "is_live_event": {"type": "boolean"},
            "title": {"type": ["string", "null"]},
            "title_ko": {"type": ["string", "null"]},
            "starts_at": {"type": ["string", "null"]},
            "venue": {"type": ["string", "null"]},
            "venue_ko": {"type": ["string", "null"]},
            "ticket_opens_at": {"type": ["string", "null"]},
            "ticket_closes_at": {"type": ["string", "null"]},
            "ticket_url": {"type": ["string", "null"]},
            "price_text": {"type": ["string", "null"]},
            "ticket_details_ko": {"type": ["string", "null"]},
            "confidence": {"type": "number"},
        },
        "required": [
            "is_live_event",
            "title",
            "title_ko",
            "starts_at",
            "venue",
            "venue_ko",
            "ticket_opens_at",
            "ticket_closes_at",
            "ticket_url",
            "price_text",
            "ticket_details_ko",
            "confidence",
        ],
    },
    "strict": True,
}


def openai_configured() -> bool:
    """OpenAI API key가 설정되어 AI 추출을 실행할 수 있는지 확인합니다."""
    return bool(settings.openai_api_key)


async def extract_music_event(
    artist_name: str,
    raw_text: str,
    page_context: str | None = None,
) -> dict[str, Any] | None:
    """X 게시물 원문에서 공연/티켓 일정 정보를 JSON 형태로 추출합니다."""
    if not settings.openai_api_key:
        return None

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "Extract J-pop live, concert, fanmeeting, festival, or ticket sales "
                    "schedule information. Return null fields when unknown. "
                    "Use ISO 8601 for date/time fields when possible. "
                    "Translate user-facing title, venue, seat, price, and application "
                    "period details into Korean. If linked page context contains seat "
                    "types, seat prices, application start/end dates, lottery periods, "
                    "or ticket sales URLs, include them in ticket_details_ko."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Artist: {artist_name}\n\nPost:\n{raw_text}\n\n"
                    f"Linked page context:\n{page_context or '(none)'}"
                ),
            },
        ],
        response_format={"type": "json_schema", "json_schema": EVENT_SCHEMA},
    )
    content = response.choices[0].message.content
    if not content:
        return None

    extracted = json.loads(content)
    if not extracted.get("is_live_event") or not extracted.get("title"):
        return None
    if float(extracted.get("confidence") or 0) < 0.55:
        return None
    if extracted.get("title_ko"):
        extracted["title"] = extracted["title_ko"]
    if extracted.get("venue_ko"):
        extracted["venue"] = extracted["venue_ko"]
    details = extracted.get("ticket_details_ko")
    if details:
        price_text = extracted.get("price_text")
        extracted["price_text"] = f"{price_text}\n\n{details}" if price_text else details
    return extracted
