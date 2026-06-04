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
            "starts_at": {"type": ["string", "null"]},
            "venue": {"type": ["string", "null"]},
            "ticket_opens_at": {"type": ["string", "null"]},
            "ticket_url": {"type": ["string", "null"]},
            "price_text": {"type": ["string", "null"]},
            "confidence": {"type": "number"},
        },
        "required": [
            "is_live_event",
            "title",
            "starts_at",
            "venue",
            "ticket_opens_at",
            "ticket_url",
            "price_text",
            "confidence",
        ],
    },
    "strict": True,
}


def openai_configured() -> bool:
    return bool(settings.openai_api_key)


async def extract_music_event(artist_name: str, raw_text: str) -> dict[str, Any] | None:
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
                    "Use ISO 8601 for date/time fields when possible."
                ),
            },
            {
                "role": "user",
                "content": f"Artist: {artist_name}\n\nPost:\n{raw_text}",
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
    return extracted
