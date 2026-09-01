"""Refresh J-POP Playlist TJ entries and apply them to existing setlists."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.db import init_db
from app.integrations.jpop_playlist_tj import apply_jpop_playlist_matches, refresh_jpop_playlist_index


def main() -> None:
    init_db()
    loaded = asyncio.run(refresh_jpop_playlist_index())
    updated = apply_jpop_playlist_matches()
    print({"source_rows_loaded": loaded, "performances_updated": updated}, flush=True)


if __name__ == "__main__":
    main()
