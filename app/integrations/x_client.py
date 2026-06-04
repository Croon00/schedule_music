from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings


X_API_BASE_URL = "https://api.x.com/2"


def x_configured() -> bool:
    return bool(settings.x_bearer_token)


async def get_x_user_id(username: str) -> str:
    if not settings.x_bearer_token:
        raise RuntimeError("X_BEARER_TOKEN is not configured.")

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{X_API_BASE_URL}/users/by/username/{username}",
            headers=_headers(),
        )
        response.raise_for_status()
        data = response.json()
    return data["data"]["id"]


async def fetch_recent_posts(user_id: str, since_id: str | None = None) -> list[dict[str, Any]]:
    if not settings.x_bearer_token:
        raise RuntimeError("X_BEARER_TOKEN is not configured.")

    params = {
        "max_results": "5",
        "tweet.fields": "created_at",
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
    return f"https://x.com/{username}/status/{post_id}"


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.x_bearer_token}"}
