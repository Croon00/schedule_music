from __future__ import annotations

import asyncio
import re
import unicodedata
from dataclasses import dataclass

import httpx

from app.core.config import settings
from app.core.db import get_connection
from app.integrations.spotify import SpotifyDiscographyTrack, get_artist_discography_tracks
from app.integrations.youtube_context import YOUTUBE_API_BASE_URL, youtube_data_api_configured


@dataclass(frozen=True)
class YouTubeAutoLinkResult:
    scanned_tracks: int = 0
    already_linked: int = 0
    linked: int = 0
    unmatched: int = 0
    enabled: bool = True


def _normalise(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).lower()
    return "".join(character for character in value if character.isalnum())


def _candidate_score(track: SpotifyDiscographyTrack, item: dict) -> int:
    snippet = item.get("snippet") or {}
    title = str(snippet.get("title") or "")
    channel = str(snippet.get("channelTitle") or "")
    norm_title = _normalise(title)
    norm_track = _normalise(track.name)
    norm_artists = [_normalise(name) for name in track.artists if _normalise(name)]
    haystack = f"{title} {channel}".lower()
    score = 0
    if norm_track and norm_track in norm_title:
        score += 70
    if any(name in norm_title or name in _normalise(channel) for name in norm_artists):
        score += 20
    if any(token in haystack for token in ("official", "公式", "mv", "music video", "lyric video")):
        score += 10
    if any(token in haystack for token in ("cover", "歌ってみた", "live", "shorts", "reaction", "踊ってみた")):
        score -= 100
    return score


async def _find_youtube_match(
    client: httpx.AsyncClient,
    track: SpotifyDiscographyTrack,
) -> tuple[str, str] | None:
    query_artist = track.artists[0] if track.artists else ""
    response = await client.get(
        f"{YOUTUBE_API_BASE_URL}/search",
        params={
            "part": "snippet",
            "q": f"{query_artist} {track.name} official",
            "type": "video",
            "maxResults": 5,
            "key": settings.youtube_api_key,
        },
    )
    response.raise_for_status()
    candidates = response.json().get("items") or []
    best = max(candidates, key=lambda item: _candidate_score(track, item), default=None)
    if not best or _candidate_score(track, best) < 80:
        return None
    video_id = str((best.get("id") or {}).get("videoId") or "")
    if not video_id:
        return None
    return video_id, f"https://www.youtube.com/watch?v={video_id}"


def _existing_track_ids(track_ids: list[str]) -> set[str]:
    if not track_ids:
        return set()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT spotify_track_id FROM songs WHERE spotify_track_id = ANY(%s)",
            (track_ids,),
        ).fetchall()
    return {str(row["spotify_track_id"]) for row in rows if row["spotify_track_id"]}


def _save_link(track: SpotifyDiscographyTrack, video_id: str, youtube_url: str) -> None:
    """Save only a confirmed automatic video link; lyrics are never created here."""
    artist_name = ", ".join(track.artists)
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO songs (
                discord_user_id, original_title, artist_name, album_name,
                youtube_url, youtube_video_id, spotify_track_id
            ) VALUES ('web', %s, %s, %s, %s, %s, %s)
            ON CONFLICT (discord_user_id, youtube_video_id) DO UPDATE
            SET original_title = EXCLUDED.original_title,
                artist_name = EXCLUDED.artist_name,
                album_name = EXCLUDED.album_name,
                spotify_track_id = EXCLUDED.spotify_track_id,
                updated_at = CURRENT_TIMESTAMP
            """,
            (track.name, artist_name, track.album_name, youtube_url, video_id, track.id),
        )
        conn.commit()


async def auto_link_spotify_artist_youtube(spotify_artist_id: str) -> YouTubeAutoLinkResult:
    """Link high-confidence official YouTube videos for unlinked Spotify tracks.

    Ambiguous results deliberately stay unlinked so the UI can offer the
    per-track URL input rather than accidentally sending users to a cover.
    """
    if not youtube_data_api_configured():
        return YouTubeAutoLinkResult(enabled=False)

    tracks = await get_artist_discography_tracks(spotify_artist_id)
    existing = _existing_track_ids([track.id for track in tracks])
    unlinked = [track for track in tracks if track.id not in existing]
    candidates = unlinked[:max(settings.youtube_auto_link_max_tracks, 1)]
    semaphore = asyncio.Semaphore(max(settings.youtube_auto_link_concurrency, 1))

    async with httpx.AsyncClient(timeout=20) as client:
        async def find(track: SpotifyDiscographyTrack):
            async with semaphore:
                try:
                    return track, await _find_youtube_match(client, track)
                except httpx.HTTPError:
                    return track, None

        matches = await asyncio.gather(*(find(track) for track in candidates))

    linked = 0
    for track, match in matches:
        if match is None:
            continue
        _save_link(track, *match)
        linked += 1
    return YouTubeAutoLinkResult(
        scanned_tracks=len(candidates),
        already_linked=len(existing),
        linked=linked,
        unmatched=len(candidates) - linked,
    )
