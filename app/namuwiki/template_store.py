from __future__ import annotations

import json
from pathlib import Path

from app.namuwiki.models import (
    NamuWikiTemplateCreate,
    NamuWikiTemplateDetail,
    NamuWikiTemplateInfo,
)


TEMPLATE_DIR = Path("data") / "namuwiki_templates"


class NamuWikiTemplateNotFoundError(KeyError):
    pass


def save_template(payload: NamuWikiTemplateCreate) -> NamuWikiTemplateDetail:
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
    path = _template_path(template_id)
    if not path.exists():
        raise NamuWikiTemplateNotFoundError(template_id)
    return _read_template_path(path)


def delete_template(template_id: str) -> None:
    path = _template_path(template_id)
    if not path.exists():
        raise NamuWikiTemplateNotFoundError(template_id)
    path.unlink()


def _template_path(template_id: str) -> Path:
    return TEMPLATE_DIR / f"{template_id}.json"


def _read_template_path(path: Path) -> NamuWikiTemplateDetail:
    return NamuWikiTemplateDetail(**json.loads(path.read_text(encoding="utf-8")))
