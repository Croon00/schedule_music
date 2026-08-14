"""Cache official X profile image URLs on artist records.

This avoids relying on third-party avatar proxy caches in the web UI.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.db import get_connection
from app.integrations.x_client import get_x_profile_image_url


async def cache_image(artist_id: int, username: str) -> str:
    image_url = await get_x_profile_image_url(username)
    with get_connection() as conn:
        conn.execute(
            """UPDATE artists SET spotify_image_url = %s, updated_at = CURRENT_TIMESTAMP
               WHERE id = %s""",
            (image_url, artist_id),
        )
        conn.commit()
    return image_url


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("artist_id", type=int)
    parser.add_argument("username")
    args = parser.parse_args()
    print(asyncio.run(cache_image(args.artist_id, args.username)))


if __name__ == "__main__":
    main()
