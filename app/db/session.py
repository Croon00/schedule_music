from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings


def get_engine() -> Engine:
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required for database access.")
    # Existing deployments use psycopg 3, not psycopg2. SQLAlchemy's bare
    # ``postgresql://`` URL otherwise selects the unavailable psycopg2 driver.
    url = settings.database_url
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return create_engine(url, pool_pre_ping=True)


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency for a transaction-scoped SQLAlchemy session."""
    factory = sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)
    with factory() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
