from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.config import settings
from app.core.db import get_connection


GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_CALENDAR_EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"
GOOGLE_SCOPE = "https://www.googleapis.com/auth/calendar.events"


def google_oauth_configured() -> bool:
    return bool(
        settings.google_client_id
        and settings.google_client_secret
        and get_google_redirect_uri()
    )


def get_google_redirect_uri() -> str | None:
    if settings.google_redirect_uri:
        return settings.google_redirect_uri
    if settings.public_base_url:
        return f"{settings.public_base_url.rstrip('/')}/auth/google/callback"
    return None


def build_google_auth_url(discord_user_id: str) -> str:
    redirect_uri = get_google_redirect_uri()
    if not settings.google_client_id or not redirect_uri:
        raise RuntimeError("Google OAuth is not configured.")

    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": GOOGLE_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": discord_user_id,
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


async def exchange_code_for_tokens(code: str, discord_user_id: str) -> None:
    redirect_uri = get_google_redirect_uri()
    if not settings.google_client_id or not settings.google_client_secret or not redirect_uri:
        raise RuntimeError("Google OAuth is not configured.")

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        response.raise_for_status()
        token = response.json()

    _store_google_token(discord_user_id, token)


async def refresh_google_token(discord_user_id: str, token: dict[str, Any]) -> dict[str, Any]:
    refresh_token = token.get("refresh_token")
    if not refresh_token:
        raise RuntimeError("Google refresh token is missing.")
    if not settings.google_client_id or not settings.google_client_secret:
        raise RuntimeError("Google OAuth is not configured.")

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
        response.raise_for_status()
        refreshed = response.json()

    refreshed["refresh_token"] = refresh_token
    _store_google_token(discord_user_id, refreshed)
    return get_google_token(discord_user_id)


def get_google_token(discord_user_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT *
            FROM google_oauth_tokens
            WHERE discord_user_id = %s
            """,
            (discord_user_id,),
        ).fetchone()


def google_connected(discord_user_id: str) -> bool:
    return get_google_token(discord_user_id) is not None


async def create_calendar_event(discord_user_id: str, event: dict[str, Any]) -> str:
    token = get_google_token(discord_user_id)
    if not token:
        raise RuntimeError("Google Calendar is not connected.")

    expires_at = token.get("expires_at")
    if expires_at and expires_at <= datetime.now(UTC) + timedelta(minutes=2):
        token = await refresh_google_token(discord_user_id, token)

    calendar_id = token.get("calendar_id") or settings.google_calendar_id
    payload = _to_google_event(event)

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            GOOGLE_CALENDAR_EVENTS_URL.format(calendar_id=calendar_id),
            headers={"Authorization": f"Bearer {token['access_token']}"},
            json=payload,
        )
        response.raise_for_status()
        created = response.json()

    return created["id"]


def _store_google_token(discord_user_id: str, token: dict[str, Any]) -> None:
    expires_at = None
    if token.get("expires_in"):
        expires_at = datetime.now(UTC) + timedelta(seconds=int(token["expires_in"]))

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO google_oauth_tokens (
                discord_user_id, access_token, refresh_token, expires_at,
                scope, token_type, calendar_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (discord_user_id) DO UPDATE SET
                access_token = EXCLUDED.access_token,
                refresh_token = COALESCE(EXCLUDED.refresh_token, google_oauth_tokens.refresh_token),
                expires_at = EXCLUDED.expires_at,
                scope = EXCLUDED.scope,
                token_type = EXCLUDED.token_type,
                calendar_id = EXCLUDED.calendar_id,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                discord_user_id,
                token["access_token"],
                token.get("refresh_token"),
                expires_at,
                token.get("scope"),
                token.get("token_type"),
                settings.google_calendar_id,
            ),
        )
        conn.commit()


def _to_google_event(event: dict[str, Any]) -> dict[str, Any]:
    description_parts = []
    if event.get("source_url"):
        description_parts.append(f"Source: {event['source_url']}")
    if event.get("raw_text"):
        description_parts.append(event["raw_text"])

    starts_at = event.get("starts_at")
    if starts_at:
        end_at = _add_default_duration(starts_at)
        return {
            "summary": event["title"],
            "location": event.get("venue"),
            "description": "\n\n".join(description_parts),
            "start": {"dateTime": starts_at},
            "end": {"dateTime": end_at},
        }

    return {
        "summary": event["title"],
        "location": event.get("venue"),
        "description": "\n\n".join(description_parts),
        "start": {"date": datetime.now(UTC).date().isoformat()},
        "end": {"date": datetime.now(UTC).date().isoformat()},
    }


def _add_default_duration(starts_at: str) -> str:
    parsed = datetime.fromisoformat(starts_at.replace("Z", "+00:00"))
    return (parsed + timedelta(hours=2)).isoformat()
