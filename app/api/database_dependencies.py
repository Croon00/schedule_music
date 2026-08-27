"""FastAPI 요청에서 사용하는 Psycopg 연결 의존성이다."""

from collections.abc import Generator

from psycopg import Connection

from app.core.db import get_connection


def get_db_connection() -> Generator[Connection, None, None]:
    """요청이 끝나면 닫히는 PostgreSQL 연결을 제공한다."""
    with get_connection() as connection:
        try:
            yield connection
        except Exception:
            connection.rollback()
            raise
