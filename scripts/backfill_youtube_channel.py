"""Run an idempotent historical utawaku archive backfill for one channel."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.integrations.youtube_channel_monitor import backfill_youtube_channel


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("channel_url")
    parser.add_argument("artist_name")
    parser.add_argument("--concurrency", type=int, default=6)
    args = parser.parse_args()
    result = asyncio.run(
        backfill_youtube_channel(
            channel_url=args.channel_url,
            artist_name=args.artist_name,
            concurrency=args.concurrency,
        )
    )
    print(result)


if __name__ == "__main__":
    main()
