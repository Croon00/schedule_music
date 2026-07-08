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


def test_placeholder_template_renders_without_openai_key() -> None:
    original_key = settings.openai_api_key
    settings.openai_api_key = None
    try:
        with TestClient(app) as client:
            response = client.post(
                "/namuwiki/song-article/from-template",
                json={
                    "template_example": (
                        "{{categories}}\n"
                        "|| 제목 || {{title}} ||\n"
                        "|| 가수 || [[{{artist}}]] ||\n"
                        "|| 작사 || {{lyricist}} ||\n"
                        "{{extra_credits}}\n"
                        "== 가사 ==\n"
                        "{{lyrics}}"
                    ),
                    "song": {
                        "title": "Song",
                        "artist": "Artist",
                        "categories": ["일본 노래"],
                        "lyricist": "Lyricist",
                        "illustrator": "Illustrator",
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

    assert response.status_code == 200
    assert response.json()["text"] == (
        "[[분류:일본 노래]]\n"
        "|| 제목 || Song ||\n"
        "|| 가수 || [[Artist]] ||\n"
        "|| 작사 || Lyricist ||\n"
        "|| '''일러스트''' ||||Illustrator ||\n"
        "== 가사 ==\n"
        "'''原文'''\n"
        "{{{#b1b1b1,#7f7f7f 발음}}}\n"
        "{{{#b1b1b1,#7f7f7f 번역}}}\n"
    )


def test_placeholder_template_can_include_video_section() -> None:
    original_key = settings.openai_api_key
    settings.openai_api_key = None
    try:
        with TestClient(app) as client:
            response = client.post(
                "/namuwiki/song-article/from-template",
                json={
                    "template_example": "before\n{{video_section}}\nafter",
                    "song": {
                        "title": "Song",
                        "artist": "Artist",
                        "youtube_url": "https://www.youtube.com/watch?v=c7m6kAGEw3U",
                    },
                },
            )
    finally:
        settings.openai_api_key = original_key

    assert response.status_code == 200
    assert "before\n== " in response.json()["text"]
    assert "[youtube(c7m6kAGEw3U)]" in response.json()["text"]
    assert "'''MV'''" in response.json()["text"]
    assert response.json()["text"].endswith("\nafter\n")


def test_placeholder_template_can_include_cover_image_and_row() -> None:
    original_key = settings.openai_api_key
    settings.openai_api_key = None
    try:
        with TestClient(app) as client:
            response = client.post(
                "/namuwiki/song-article/from-template",
                json={
                    "template_example": "{{cover_row}}\nimage={{cover_image}}",
                    "song": {
                        "title": "Song",
                        "artist": "Artist",
                        "cover_file": "Cover_Brand_New_Episode.jpg",
                    },
                },
            )
    finally:
        settings.openai_api_key = original_key

    assert response.status_code == 200
    assert (
        "||<-3><bgcolor=#fff,#2d2f34><nopad> "
        "[[파일:Cover_Brand_New_Episode.jpg|width=100%]] ||"
    ) in response.json()["text"]
    assert "image=[[파일:Cover_Brand_New_Episode.jpg|width=100%]]" in response.json()["text"]


def test_saved_template_can_be_created_listed_and_read(tmp_path: Path) -> None:
    original_dir = template_store.TEMPLATE_DIR
    test_dir = tmp_path / "namuwiki_templates"
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


def test_saved_template_render_requires_openai_key(tmp_path: Path) -> None:
    original_dir = template_store.TEMPLATE_DIR
    original_key = settings.openai_api_key
    test_dir = tmp_path / "namuwiki_templates"
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
