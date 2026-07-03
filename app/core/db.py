from __future__ import annotations

from typing import Any

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row

from app.core.config import settings


def get_connection() -> Connection:
    """환경변수 DATABASE_URL로 PostgreSQL 연결을 만들고 row를 dict 형태로 반환합니다."""
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required for database-backed routes.")
    return psycopg.connect(settings.database_url, row_factory=dict_row)


def init_db() -> None:
    """앱 실행에 필요한 PostgreSQL 테이블과 기존 DB의 누락 컬럼을 준비합니다."""
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS artists (
                id SERIAL PRIMARY KEY,
                discord_user_id TEXT,
                name TEXT NOT NULL,
                display_name TEXT,
                notes TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS artist_sources (
                id SERIAL PRIMARY KEY,
                artist_id INTEGER NOT NULL,
                source_type TEXT NOT NULL,
                label TEXT,
                value TEXT NOT NULL,
                external_user_id TEXT,
                last_seen_external_id TEXT,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (artist_id) REFERENCES artists(id) ON DELETE CASCADE,
                UNIQUE (artist_id, source_type, value)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS event_candidates (
                id SERIAL PRIMARY KEY,
                artist_id INTEGER,
                discord_user_id TEXT,
                source_id INTEGER,
                title TEXT NOT NULL,
                starts_at TEXT,
                venue TEXT,
                ticket_opens_at TEXT,
                ticket_closes_at TEXT,
                ticket_url TEXT,
                price_text TEXT,
                source_url TEXT,
                raw_text TEXT,
                status TEXT NOT NULL DEFAULT 'needs_review',
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (artist_id) REFERENCES artists(id) ON DELETE SET NULL,
                FOREIGN KEY (source_id) REFERENCES artist_sources(id) ON DELETE SET NULL
            )
            """
        )
        conn.execute("ALTER TABLE artists ADD COLUMN IF NOT EXISTS discord_user_id TEXT")
        conn.execute("ALTER TABLE artist_sources ADD COLUMN IF NOT EXISTS external_user_id TEXT")
        conn.execute("ALTER TABLE artist_sources ADD COLUMN IF NOT EXISTS last_seen_external_id TEXT")
        conn.execute("ALTER TABLE event_candidates ADD COLUMN IF NOT EXISTS discord_user_id TEXT")
        conn.execute("ALTER TABLE event_candidates ADD COLUMN IF NOT EXISTS ticket_closes_at TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS google_oauth_tokens (
                discord_user_id TEXT PRIMARY KEY,
                access_token TEXT NOT NULL,
                refresh_token TEXT,
                expires_at TIMESTAMPTZ,
                scope TEXT,
                token_type TEXT,
                calendar_id TEXT NOT NULL DEFAULT 'primary',
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS source_items (
                id SERIAL PRIMARY KEY,
                discord_user_id TEXT NOT NULL,
                source_id INTEGER,
                external_id TEXT NOT NULL,
                url TEXT,
                published_at TIMESTAMPTZ,
                raw_text TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (source_id) REFERENCES artist_sources(id) ON DELETE SET NULL,
                UNIQUE (discord_user_id, source_id, external_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS calendar_syncs (
                id SERIAL PRIMARY KEY,
                discord_user_id TEXT NOT NULL,
                event_candidate_id INTEGER NOT NULL,
                provider TEXT NOT NULL DEFAULT 'google',
                event_type TEXT NOT NULL DEFAULT 'live',
                provider_event_id TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (event_candidate_id) REFERENCES event_candidates(id) ON DELETE CASCADE,
                UNIQUE (discord_user_id, event_candidate_id, provider)
            )
            """
        )
        conn.execute("ALTER TABLE calendar_syncs ADD COLUMN IF NOT EXISTS event_type TEXT NOT NULL DEFAULT 'live'")
        conn.execute(
            """
            ALTER TABLE calendar_syncs
            DROP CONSTRAINT IF EXISTS calendar_syncs_discord_user_id_event_candidate_id_provider_key
            """
        )
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS calendar_syncs_unique_event_type
            ON calendar_syncs (discord_user_id, event_candidate_id, provider, event_type)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS songs (
                id SERIAL PRIMARY KEY,
                discord_user_id TEXT,
                original_title TEXT NOT NULL,
                title_ko TEXT,
                artist_name TEXT NOT NULL,
                artist_name_ko TEXT,
                album_name TEXT,
                album_name_ko TEXT,
                release_date TEXT,
                language_code TEXT,
                duration_ms INTEGER,
                youtube_url TEXT NOT NULL,
                youtube_video_id TEXT NOT NULL,
                spotify_track_id TEXT,
                spotify_url TEXT,
                spotify_album_id TEXT,
                spotify_artist_ids TEXT[],
                cover_image_url TEXT,
                spotify_raw JSONB,
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (discord_user_id, youtube_video_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS song_lyrics (
                id SERIAL PRIMARY KEY,
                song_id INTEGER NOT NULL,
                original_lyrics TEXT NOT NULL,
                translation_ko TEXT NOT NULL,
                pronunciation_ko TEXT NOT NULL,
                lyrics_source_type TEXT NOT NULL,
                lyrics_source_url TEXT,
                translation_model TEXT,
                needs_review BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (song_id) REFERENCES songs(id) ON DELETE CASCADE,
                UNIQUE (song_id)
            )
            """
        )
        conn.commit()


def row_to_dict(row: dict[str, Any] | None) -> dict[str, Any] | None:
    """psycopg row를 일반 dict로 바꾸고, row가 없으면 None을 그대로 반환합니다."""
    if row is None:
        return None
    return dict(row)
