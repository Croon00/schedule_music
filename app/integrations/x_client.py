from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings


X_API_BASE_URL = "https://api.x.com/2"


def x_configured() -> bool:
    """X API 호출에 필요한 bearer token이 설정되어 있는지 확인합니다."""
    return bool(settings.x_bearer_token)


async def get_x_user_id(username: str) -> str:
    """X username을 X API 내부 user id로 변환합니다."""
    if not settings.x_bearer_token:
        raise RuntimeError("X_BEARER_TOKEN이 설정되어 있지 않습니다.")

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{X_API_BASE_URL}/users/by/username/{username}",
            headers=_headers(),
        )
        response.raise_for_status()
        data = response.json()
    return data["data"]["id"]


async def fetch_recent_posts(
    user_id: str,
    since_id: str | None = None,
    *,
    max_results: int = 5,
) -> list[dict[str, Any]]:
    """특정 X user id의 최신 원본 게시물을 가져오고, since_id 이후만 조회할 수 있습니다."""
    if not settings.x_bearer_token:
        raise RuntimeError("X_BEARER_TOKEN이 설정되어 있지 않습니다.")

    if not 5 <= max_results <= 100:
        raise ValueError("max_results must be between 5 and 100.")

    params = {
        "max_results": str(max_results),
        "tweet.fields": "created_at,entities",
        "exclude": "retweets,replies",
    }
    if since_id:
        params["since_id"] = since_id

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{X_API_BASE_URL}/users/{user_id}/tweets",
            headers=_headers(),
            params=params,
        )
        response.raise_for_status()
        data = response.json()

    return data.get("data", [])


def post_url(username: str, post_id: str) -> str:
    """X username과 게시물 ID로 브라우저에서 열 수 있는 게시물 URL을 만듭니다."""
    return f"https://x.com/{username}/status/{post_id}"


def _headers() -> dict[str, str]:
    """X API 요청에 공통으로 사용하는 Authorization header를 만듭니다."""
    return {"Authorization": f"Bearer {settings.x_bearer_token}"}
