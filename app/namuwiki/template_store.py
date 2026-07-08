from __future__ import annotations

import json
from pathlib import Path

from app.core.config import settings
from app.core.db import get_connection
from app.namuwiki.models import (
    NamuWikiTemplateCreate,
    NamuWikiTemplateDetail,
    NamuWikiTemplateInfo,
)


TEMPLATE_DIR = Path("data") / "namuwiki_templates"


class NamuWikiTemplateNotFoundError(KeyError):
    pass


def save_template(payload: NamuWikiTemplateCreate) -> NamuWikiTemplateDetail:
    if settings.database_url:
        return _save_template_db(payload)

    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    detail = NamuWikiTemplateDetail(
        template_id=payload.template_id,
        name=payload.name,
        description=payload.description,
        template_example=payload.template_example,
    )
    _template_path(payload.template_id).write_text(
        detail.model_dump_json(indent=2),
        encoding="utf-8",
    )
    return detail


def list_templates() -> list[NamuWikiTemplateInfo]:
    if settings.database_url:
        return _list_templates_db()

    if not TEMPLATE_DIR.exists():
        return []

    templates = []
    for path in sorted(TEMPLATE_DIR.glob("*.json")):
        detail = _read_template_path(path)
        templates.append(
            NamuWikiTemplateInfo(
                template_id=detail.template_id,
                name=detail.name,
                description=detail.description,
            )
        )
    return templates


def get_template(template_id: str) -> NamuWikiTemplateDetail:
    if settings.database_url:
        return _get_template_db(template_id)

    path = _template_path(template_id)
    if not path.exists():
        raise NamuWikiTemplateNotFoundError(template_id)
    return _read_template_path(path)


def delete_template(template_id: str) -> None:
    if settings.database_url:
        _delete_template_db(template_id)
        return

    path = _template_path(template_id)
    if not path.exists():
        raise NamuWikiTemplateNotFoundError(template_id)
    path.unlink()


def _template_path(template_id: str) -> Path:
    return TEMPLATE_DIR / f"{template_id}.json"


def _read_template_path(path: Path) -> NamuWikiTemplateDetail:
    return NamuWikiTemplateDetail(**json.loads(path.read_text(encoding="utf-8")))


def _ensure_template_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS namuwiki_templates (
            template_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            template_example TEXT NOT NULL,
            discord_user_id TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute("ALTER TABLE namuwiki_templates ADD COLUMN IF NOT EXISTS discord_user_id TEXT")


def _save_template_db(payload: NamuWikiTemplateCreate) -> NamuWikiTemplateDetail:
    detail = NamuWikiTemplateDetail(
        template_id=payload.template_id,
        name=payload.name,
        description=payload.description,
        template_example=payload.template_example,
    )
    with get_connection() as conn:
        _ensure_template_table(conn)
        conn.execute(
            """
            INSERT INTO namuwiki_templates (
                template_id, name, description, template_example
            )
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (template_id) DO UPDATE
            SET name = EXCLUDED.name,
                description = EXCLUDED.description,
                template_example = EXCLUDED.template_example,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                detail.template_id,
                detail.name,
                detail.description,
                detail.template_example,
            ),
        )
        conn.commit()
    return detail


def _list_templates_db() -> list[NamuWikiTemplateInfo]:
    with get_connection() as conn:
        _ensure_template_table(conn)
        rows = conn.execute(
            """
            SELECT template_id, name, description
            FROM namuwiki_templates
            ORDER BY template_id
            """
        ).fetchall()
    return [
        NamuWikiTemplateInfo(
            template_id=row["template_id"],
            name=row["name"],
            description=row["description"],
        )
        for row in rows
    ]


def _get_template_db(template_id: str) -> NamuWikiTemplateDetail:
    with get_connection() as conn:
        _ensure_template_table(conn)
        row = conn.execute(
            """
            SELECT template_id, name, description, template_example
            FROM namuwiki_templates
            WHERE template_id = %s
            """,
            (template_id,),
        ).fetchone()
    if row is None:
        raise NamuWikiTemplateNotFoundError(template_id)
    return NamuWikiTemplateDetail(
        template_id=row["template_id"],
        name=row["name"],
        description=row["description"],
        template_example=row["template_example"],
    )


def _delete_template_db(template_id: str) -> None:
    with get_connection() as conn:
        _ensure_template_table(conn)
        cursor = conn.execute(
            "DELETE FROM namuwiki_templates WHERE template_id = %s",
            (template_id,),
        )
        conn.commit()
    if cursor.rowcount == 0:
        raise NamuWikiTemplateNotFoundError(template_id)
