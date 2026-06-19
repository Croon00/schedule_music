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
                    "J-pop 라이브, 콘서트, 팬미팅, 페스티벌, 티켓 판매 일정 정보를 추출하세요. "
                    "알 수 없는 필드는 null로 반환하세요. 날짜와 시간은 가능하면 ISO 8601 형식을 사용하세요. "
                    "사용자에게 보이는 제목, 장소, 좌석, 가격, 신청 기간 정보는 한국어로 번역하세요. "
                    "연결된 페이지 문맥에 좌석 종류, 좌석 가격, 신청 시작/종료일, 추첨 기간, "
                    "티켓 판매 URL이 있으면 ticket_details_ko에 포함하세요."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"아티스트: {artist_name}\n\n게시물:\n{raw_text}\n\n"
                    f"연결 페이지 문맥:\n{page_context or '(없음)'}"
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
