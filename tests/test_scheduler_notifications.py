import asyncio

from app.agents import scheduler
from app.agents.scheduler import _build_notification_message, _extract_post_urls


def test_notification_message_is_compact_and_marks_live_information() -> None:
    message = _build_notification_message(
        source={"artist_name": "MEDA", "x_username": "medazcd"},
        post={"id": "2081514911042031870", "text": "long post body"},
        item_type="live_event",
        classification_reason="keyword live",
        event={"title": "MEDA live", "starts_at": "2026-07-27T20:00:00+09:00"},
    )

    assert message == (
        "MEDA (\ubd84\ub958: [!!\ub77c\uc774\ube0c \uc815\ubcf4])\n"
        "https://x.com/medazcd/status/2081514911042031870"
    )
    assert "long post body" not in message
    assert "keyword live" not in message


def test_ticket_is_also_marked_as_live_information() -> None:
    message = _build_notification_message(
        source={"artist_name": "HACHI", "x_username": "8HaChi_hacchi"},
        post={"id": "1", "text": "ticket body"},
        item_type="ticket",
        classification_reason=None,
        event=None,
    )

    assert "(\ubd84\ub958: [!!\ub77c\uc774\ube0c \uc815\ubcf4])" in message


def test_youtube_live_is_labeled_separately() -> None:
    message = _build_notification_message(
        source={"artist_name": "HACHI", "x_username": "8HaChi_hacchi"},
        post={
            "id": "3",
            "text": "YouTube live",
            "entities": {
                "urls": [
                    {
                        "expanded_url": "https://www.youtube.com/watch?v=abcdefghijk"
                    }
                ]
            },
        },
        item_type="live_event",
        classification_reason=None,
        event=None,
    )

    assert "(분류: 유튜브 라이브)" in message


def test_release_is_labeled_as_music() -> None:
    message = _build_notification_message(
        source={"artist_name": "HACHI", "x_username": "8HaChi_hacchi"},
        post={"id": "2", "text": "new music body"},
        item_type="release",
        classification_reason=None,
        event=None,
    )

    assert "(분류: 음악)" in message
    assert "신곡" not in message


def test_x_status_and_media_urls_are_not_used_as_page_context() -> None:
    post = {
        "entities": {
            "urls": [
                {"expanded_url": "https://x.com/medazcd/status/1/photo/1"},
                {"expanded_url": "https://twitter.com/medazcd/status/1"},
                {"expanded_url": "https://www.youtube.com/watch?v=abc"},
            ]
        }
    }

    assert _extract_post_urls(post) == ["https://www.youtube.com/watch?v=abc"]


def test_x_source_posts_are_not_classified_before_notification(monkeypatch) -> None:
    post = {
        "id": "10",
        "text": "ordinary post",
        "created_at": "2026-08-17T00:00:00Z",
        "entities": {"urls": []},
    }
    source = {
        "id": 1,
        "artist_id": 1,
        "x_username": "artist",
        "external_user_id": "u1",
        "last_seen_external_id": None,
        "artist_name": "Artist",
        "discord_user_id": "user1",
    }
    notified = []

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("classification should not run for immediate notifications")

    async def fake_notify(**kwargs):
        notified.append(kwargs)
        return {"sent": 1, "skipped": 0}

    async def fake_fetch_recent_posts(*args):
        return [post]

    monkeypatch.setattr(scheduler, "fetch_recent_posts", fake_fetch_recent_posts)
    monkeypatch.setattr(scheduler, "run_music_item_graph", fail_if_called, raising=False)
    monkeypatch.setattr(scheduler, "_insert_source_item", lambda *args: 123)
    monkeypatch.setattr(scheduler, "update_source_item_classification", lambda **kwargs: None)
    monkeypatch.setattr(scheduler, "_register_youtube_live_links", lambda **kwargs: None)
    monkeypatch.setattr(scheduler, "_notify_discord_routes", fake_notify)
    monkeypatch.setattr(scheduler, "_update_last_seen", lambda *args: None)

    result = asyncio.run(scheduler._process_x_source(source))

    assert result["notifications_sent"] == 1
    assert notified[0]["item_type"] == "notice"
    assert notified[0]["classification_reason"] is None
    assert notified[0]["event"] is None
