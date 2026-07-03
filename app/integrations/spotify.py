from __future__ import annotations

import base64
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings


SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_SEARCH_URL = "https://api.spotify.com/v1/search"


class SpotifyTrackInfo(BaseModel):
    """Spotify 검색 결과에서 곡 저장에 필요한 핵심 메타데이터입니다."""

    model_config = ConfigDict(frozen=True)

    track_id: str = Field(min_length=1)
    name: str
    artists: list[str]
    artist_ids: list[str]
    album_id: str | None = None
    album_name: str | None = None
    release_date: str | None = None
    duration_ms: int | None = None
    spotify_url: str | None = None
    cover_image_url: str | None = None
    raw: dict[str, Any]


def spotify_configured() -> bool:
    return bool(settings.spotify_client_id and settings.spotify_client_secret)


async def _get_spotify_access_token() -> str:
    if not settings.spotify_client_id or not settings.spotify_client_secret:
        raise RuntimeError("Spotify API credentials are not configured.")

    credentials = f"{settings.spotify_client_id}:{settings.spotify_client_secret}"
    encoded = base64.b64encode(credentials.encode("utf-8")).decode("ascii")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            SPOTIFY_TOKEN_URL,
            headers={"Authorization": f"Basic {encoded}"},
            data={"grant_type": "client_credentials"},
        )
        response.raise_for_status()
        data = response.json()
    return str(data["access_token"])


async def search_spotify_track(artist: str, title: str) -> SpotifyTrackInfo | None:
    """아티스트명과 곡 제목으로 Spotify track을 검색해 첫 번째 후보를 반환합니다."""
    if not spotify_configured():
        return None

    token = await _get_spotify_access_token()
    query = f'track:"{title}" artist:"{artist}"'
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            SPOTIFY_SEARCH_URL,
            headers={"Authorization": f"Bearer {token}"},
            params={"q": query, "type": "track", "limit": 1},
        )
        response.raise_for_status()
        data = response.json()

    items = ((data.get("tracks") or {}).get("items") or [])
    if not items:
        return None
    return spotify_track_from_api_item(items[0])


def spotify_track_from_api_item(item: dict[str, Any]) -> SpotifyTrackInfo:
    album = item.get("album") or {}
    artists = item.get("artists") or []
    images = album.get("images") or []
    external_urls = item.get("external_urls") or {}

    return SpotifyTrackInfo(
        track_id=str(item["id"]),
        name=str(item.get("name") or ""),
        artists=[str(artist.get("name") or "") for artist in artists if artist.get("name")],
        artist_ids=[str(artist.get("id") or "") for artist in artists if artist.get("id")],
        album_id=album.get("id"),
        album_name=album.get("name"),
        release_date=album.get("release_date"),
        duration_ms=item.get("duration_ms"),
        spotify_url=external_urls.get("spotify"),
        cover_image_url=(images[0] or {}).get("url") if images else None,
        raw=item,
    )
