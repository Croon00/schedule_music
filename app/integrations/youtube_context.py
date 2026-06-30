from __future__ import annotations

import json
from dataclasses import dataclass

import httpx
from openai import AsyncOpenAI

from app.core.config import settings


YOUTUBE_API_BASE_URL = "https://www.googleapis.com/youtube/v3"
LYRICS_CONTEXT_SCHEMA = {
    "name": "lyrics_context_extract",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "is_lyrics_candidate": {"type": "boolean"},
            "excerpt": {"type": "string"},
            "reason_ko": {"type": "string"},
        },
        "required": ["is_lyrics_candidate", "excerpt", "reason_ko"],
    },
    "strict": True,
}


@dataclass(frozen=True)
class YouTubeContextText:
    source: str
    text: str


def youtube_data_api_configured() -> bool:
    """YouTube Data API key가 설정되어 있는지 확인합니다."""
    return bool(settings.youtube_api_key)


async def fetch_video_description(video_id: str) -> YouTubeContextText | None:
    """YouTube Data API로 영상 설명란을 가져옵니다."""
    if not settings.youtube_api_key:
        raise RuntimeError("YOUTUBE_API_KEY가 설정되어 있지 않습니다.")

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{YOUTUBE_API_BASE_URL}/videos",
            params={
                "part": "snippet",
                "id": video_id,
                "key": settings.youtube_api_key,
            },
        )
        response.raise_for_status()
        data = response.json()

    items = data.get("items") or []
    if not items:
        return None
    description = (items[0].get("snippet") or {}).get("description") or ""
    description = description.strip()
    if not description:
        return None
    return YouTubeContextText(source="description", text=description)


async def fetch_top_comment(video_id: str) -> YouTubeContextText | None:
    """YouTube Data API로 관련도 기준 상단 댓글 하나를 가져옵니다."""
    if not settings.youtube_api_key:
        raise RuntimeError("YOUTUBE_API_KEY가 설정되어 있지 않습니다.")

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{YOUTUBE_API_BASE_URL}/commentThreads",
            params={
                "part": "snippet",
                "videoId": video_id,
                "maxResults": "1",
                "order": "relevance",
                "textFormat": "plainText",
                "key": settings.youtube_api_key,
            },
        )
        response.raise_for_status()
        data = response.json()

    items = data.get("items") or []
    if not items:
        return None
    snippet = ((items[0].get("snippet") or {}).get("topLevelComment") or {}).get("snippet") or {}
    text = (snippet.get("textOriginal") or snippet.get("textDisplay") or "").strip()
    if not text:
        return None
    return YouTubeContextText(source="top_comment", text=text)


async def extract_lyrics_candidate(text: str, source_name: str) -> tuple[str, str] | None:
    """설명란/댓글 텍스트에서 가사로 보이는 짧은 후보 구간을 추출합니다."""
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY가 설정되어 있지 않습니다.")

    max_chars = settings.lyrics_context_extract_max_chars
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "주어진 YouTube 설명란 또는 댓글에서 노래 가사로 보이는 부분이 있는지 판단하세요. "
                    "가사라는 단어가 없어도 절취선, 여러 줄로 이어진 시적 문장, 반복구, 곡 구조처럼 "
                    "보이면 후보로 볼 수 있습니다. 전체 가사를 길게 반환, 가사 후보가 아니면 "
                    "is_lyrics_candidate=false와 빈 excerpt를 반환하세요."
                ),
            },
            {
                "role": "user",
                "content": f"출처: {source_name}\n\n본문:\n{text[:12000]}",
            },
        ],
        response_format={"type": "json_schema", "json_schema": LYRICS_CONTEXT_SCHEMA},
    )
    content = response.choices[0].message.content
    if not content:
        return None

    data = json.loads(content)
    excerpt = str(data.get("excerpt") or "").strip()
    if not data.get("is_lyrics_candidate") or not excerpt:
        return None
    return excerpt[:max_chars], str(data.get("reason_ko") or "").strip()
