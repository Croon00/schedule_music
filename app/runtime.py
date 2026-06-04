from __future__ import annotations

import asyncio
import logging
import os

import uvicorn

from app.agents.scheduler import agent_loop
from app.api.main import app
from app.bots.discord_bot import start_discord_bot


async def _serve_api() -> None:
    port = int(os.getenv("PORT", "8000"))
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    await asyncio.gather(
        _serve_api(),
        start_discord_bot(),
        agent_loop(),
    )


if __name__ == "__main__":
    asyncio.run(main())
