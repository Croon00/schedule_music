import os

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="PostgreSQL API tests require TEST_DATABASE_URL.",
)


def test_artist_can_be_created_with_x_username() -> None:
    settings.database_url = os.environ["TEST_DATABASE_URL"]

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


def test_source_can_be_added_to_artist() -> None:
    settings.database_url = os.environ["TEST_DATABASE_URL"]

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
