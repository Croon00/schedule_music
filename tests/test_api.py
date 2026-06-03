from pathlib import Path

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def test_artist_can_be_created_with_x_username(tmp_path: Path) -> None:
    settings.database_path = str(tmp_path / "test.db")

    with TestClient(app) as client:
        response = client.post(
            "/artists",
            json={"name": "YOASOBI", "x_username": "@YOASOBI_staff"},
        )

        assert response.status_code == 201
        body = response.json()
        assert body["name"] == "YOASOBI"
        assert body["sources"][0]["source_type"] == "x"
        assert body["sources"][0]["value"] == "YOASOBI_staff"


def test_source_can_be_added_to_artist(tmp_path: Path) -> None:
    settings.database_path = str(tmp_path / "test.db")

    with TestClient(app) as client:
        artist = client.post("/artists", json={"name": "Ado"}).json()
        response = client.post(
            f"/artists/{artist['id']}/sources",
            json={
                "source_type": "official_site",
                "label": "Official news",
                "value": "https://www.universal-music.co.jp/ado/news/",
            },
        )

        assert response.status_code == 201
        assert response.json()["source_type"] == "official_site"
