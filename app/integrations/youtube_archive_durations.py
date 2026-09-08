"""Refresh saved archive durations without deleting archives or setlists.

Run with python -m app.integrations.youtube_archive_durations.
"""

import asyncio
import re

import httpx

from app.core.config import settings
from app.core.db import get_connection
from app.integrations.youtube_context import YOUTUBE_API_BASE_URL


def parse_duration(value: str) -> int | None:
    match = re.fullmatch(r"P(?:(\d+)D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value)
    if not match or not any(match.groups()):
        return None
    return sum(int(part or 0) * scale for part, scale in zip(match.groups(), (86400, 3600, 60, 1)))


async def refresh_archive_durations() -> dict[str, int]:
    if not settings.youtube_api_key:
        raise RuntimeError("YOUTUBE_API_KEY is not configured")
    with get_connection() as conn:
        conn.execute("ALTER TABLE youtube_live_archives ADD COLUMN IF NOT EXISTS duration_seconds INTEGER")
        rows = conn.execute("SELECT DISTINCT youtube_video_id FROM youtube_live_archives ORDER BY youtube_video_id").fetchall()
        conn.commit()
    result = {"videos": len(rows), "checked": 0, "unavailable": 0, "excluded_rows": 0}
    async with httpx.AsyncClient(timeout=30) as client:
        for offset in range(0, len(rows), 50):
            batch = rows[offset:offset + 50]
            response = await client.get(f"{YOUTUBE_API_BASE_URL}/videos", params={
                "part": "contentDetails", "id": ",".join(row["youtube_video_id"] for row in batch),
                "key": settings.youtube_api_key,
            })
            if response.status_code != 200:
                raise RuntimeError(f"YouTube duration lookup failed (HTTP {response.status_code})")
            items = response.json().get("items") or []
            result["unavailable"] += len(batch) - len(items)
            with get_connection() as conn:
                for item in items:
                    duration = parse_duration((item.get("contentDetails") or {}).get("duration", ""))
                    if duration is None:
                        result["unavailable"] += 1
                        continue
                    conn.execute("UPDATE youtube_live_archives SET duration_seconds = %s WHERE youtube_video_id = %s", (duration, item["id"]))
                    result["checked"] += 1
                conn.commit()
            print(f"Checked {min(offset + 50, len(rows))}/{len(rows)} videos", flush=True)
    with get_connection() as conn:
        result["excluded_rows"] = conn.execute("SELECT COUNT(*) AS total FROM youtube_live_archives WHERE duration_seconds <= 420").fetchone()["total"]
    return result


if __name__ == "__main__":
    print(asyncio.run(refresh_archive_durations()))
