"""HTTP security dependencies.

Authentication is opt-in during the migration: setting ``API_KEY`` protects
all routers using ``require_api_key`` without exposing secrets in API docs or
logs. OAuth callbacks remain public by design.
"""

from fastapi import Header, HTTPException, status

from app.core.config import settings


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key.")
