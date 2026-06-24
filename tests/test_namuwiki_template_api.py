import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.namuwiki import template_store


def test_template_article_requires_openai_key() -> None:
    original_key = settings.openai_api_key
    settings.openai_api_key = None
    try:
        with TestClient(app) as client:
            response = client.post(
                "/namuwiki/song-article/from-template",
                json={
                    "template_example": "[[분류:일본 노래]]\n== 개요 ==\n예시",
                    "song": {
                        "title": "Song",
                        "artist": "Artist",
                        "lyrics": [
                            {
                                "original": "原文",
                                "pronunciation_ko": "발음",
                                "translation_ko": "번역",
                            }
                        ],
                    },
                },
            )
    finally:
        settings.openai_api_key = original_key

    assert response.status_code == 400
    assert response.json()["detail"] == "OPENAI_API_KEY is required."


def test_saved_template_can_be_created_listed_and_read() -> None:
    original_dir = template_store.TEMPLATE_DIR
    test_dir = Path("data") / "test_namuwiki_templates"
    shutil.rmtree(test_dir, ignore_errors=True)
    template_store.TEMPLATE_DIR = test_dir
    try:
        with TestClient(app) as client:
            created = client.post(
                "/namuwiki/templates",
                json={
                    "template_id": "hachi_dusk",
                    "name": "HACHI DUSK style",
                    "description": "HACHI single page with detailed credits",
                    "template_example": "[[category:music]]\n== overview ==\nexample",
                },
            )
            listed = client.get("/namuwiki/templates")
            detail = client.get("/namuwiki/templates/hachi_dusk")
    finally:
        template_store.TEMPLATE_DIR = original_dir
        shutil.rmtree(test_dir, ignore_errors=True)

    assert created.status_code == 200
    assert created.json()["template_id"] == "hachi_dusk"
    assert listed.status_code == 200
    assert listed.json() == [
        {
            "template_id": "hachi_dusk",
            "name": "HACHI DUSK style",
            "description": "HACHI single page with detailed credits",
        }
    ]
    assert detail.status_code == 200
    assert detail.json()["template_example"] == "[[category:music]]\n== overview ==\nexample"


def test_saved_template_render_requires_openai_key() -> None:
    original_dir = template_store.TEMPLATE_DIR
    original_key = settings.openai_api_key
    test_dir = Path("data") / "test_namuwiki_templates"
    shutil.rmtree(test_dir, ignore_errors=True)
    template_store.TEMPLATE_DIR = test_dir
    settings.openai_api_key = None
    try:
        with TestClient(app) as client:
            client.post(
                "/namuwiki/templates",
                json={
                    "template_id": "hachi_dusk",
                    "name": "HACHI DUSK style",
                    "template_example": "[[category:music]]",
                },
            )
            response = client.post(
                "/namuwiki/song-article/from-saved-template",
                json={
                    "template_id": "hachi_dusk",
                    "song": {
                        "title": "Song",
                        "artist": "Artist",
                    },
                },
            )
    finally:
        template_store.TEMPLATE_DIR = original_dir
        settings.openai_api_key = original_key
        shutil.rmtree(test_dir, ignore_errors=True)

    assert response.status_code == 400
    assert response.json()["detail"] == "OPENAI_API_KEY is required."
