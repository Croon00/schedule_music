from __future__ import annotations

import json
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings


class MusicEventExtraction(BaseModel):
    """LLM이 추출한 음악 이벤트 후보를 검증하는 Pydantic 모델입니다."""

    model_config = ConfigDict(extra="forbid")

    is_live_event: bool
    title: str | None = Field(...)
    title_ko: str | None = Field(...)
    starts_at: str | None = Field(...)
    venue: str | None = Field(...)
    venue_ko: str | None = Field(...)
    ticket_opens_at: str | None = Field(...)
    ticket_closes_at: str | None = Field(...)
    ticket_url: str | None = Field(...)
    price_text: str | None = Field(...)
    ticket_details_ko: str | None = Field(...)
    confidence: float = Field(ge=0, le=1)

    def to_event_candidate(self) -> dict[str, Any] | None:
        """검증된 추출 결과를 DB 저장에 쓰는 일정 후보 dict로 변환합니다."""
        if not self.is_live_event or not self.title or self.confidence < 0.55:
            return None

        event = self.model_dump()
        if self.title_ko:
            event["title"] = self.title_ko
        if self.venue_ko:
            event["venue"] = self.venue_ko
        if self.ticket_details_ko:
            price_text = self.price_text
            event["price_text"] = (
                f"{price_text}\n\n{self.ticket_details_ko}"
                if price_text
                else self.ticket_details_ko
            )
        return event


EVENT_SCHEMA = {
    "name": "music_event_extraction",
    "schema": MusicEventExtraction.model_json_schema(),
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
    """X 게시물 원문에서 공연/예매 일정 정보를 Pydantic 모델로 검증해 추출합니다."""
    if not settings.openai_api_key:
        return None

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "J-pop 라이브, 콘서트, 이벤트, 예매, 응모 일정 정보를 추출하세요. "
                    "알 수 없는 필드는 null로 반환하세요. 날짜와 시간은 가능하면 ISO 8601 형식을 사용하세요. "
                    "사용자에게 보이는 제목, 장소, 좌석, 가격, 신청 기간 정보는 한국어로 번역하세요. "
                    "연결된 페이지 문맥에 좌석 종류, 좌석 가격, 신청 시작/종료일, 예매 URL이 있으면 "
                    "ticket_details_ko에 포함하세요."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"아티스트: {artist_name}\n\n게시물\n{raw_text}\n\n"
                    f"연결 페이지 문맥:\n{page_context or '(없음)'}"
                ),
            },
        ],
        response_format={"type": "json_schema", "json_schema": EVENT_SCHEMA},
    )
    content = response.choices[0].message.content
    if not content:
        return None

    extraction = MusicEventExtraction.model_validate(json.loads(content))
    return extraction.to_event_candidate()
