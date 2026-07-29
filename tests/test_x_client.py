from datetime import datetime, timezone
from types import SimpleNamespace

from app.integrations import x_client


def test_auto_provider_prefers_twscrape_when_cookies_are_configured(
    monkeypatch,
) -> None:
    monkeypatch.setattr(x_client.settings, "x_provider", "auto")
    monkeypatch.setattr(x_client.settings, "twscrape_auth_token", "auth")
    monkeypatch.setattr(x_client.settings, "twscrape_ct0", "csrf")
    monkeypatch.setattr(x_client.settings, "x_bearer_token", "bearer")

    assert x_client.x_provider() == "twscrape"
    assert x_client.x_configured() is True


def test_x_api_can_be_selected_for_rollback(monkeypatch) -> None:
    monkeypatch.setattr(x_client.settings, "x_provider", "x_api")
    monkeypatch.setattr(x_client.settings, "x_bearer_token", "bearer")

    assert x_client.x_provider() == "x_api"
    assert x_client.x_configured() is True


def test_tweet_is_converted_to_existing_scheduler_shape() -> None:
    tweet = SimpleNamespace(
        id=123,
        rawContent="new song",
        date=datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc),
        links=[
            SimpleNamespace(
                url="https://example.com/release",
                tcourl="https://t.co/example",
            )
        ],
    )

    assert x_client._tweet_to_post(tweet) == {
        "id": "123",
        "text": "new song",
        "created_at": "2026-07-29T12:00:00+00:00",
        "entities": {
            "urls": [
                {
                    "url": "https://t.co/example",
                    "expanded_url": "https://example.com/release",
                }
            ]
        },
    }
