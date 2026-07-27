from app.agents.scheduler import _build_notification_message, _extract_post_urls


def test_notification_message_is_compact_and_keeps_one_bare_x_url() -> None:
    message = _build_notification_message(
        source={"artist_name": "MEDA", "x_username": "medazcd"},
        post={"id": "2081514911042031870", "text": "long post body"},
        item_type="live_event",
        classification_reason="keyword live",
        event={"title": "MEDA live", "starts_at": "2026-07-27T20:00:00+09:00"},
    )

    assert message == (
        "MEDA (분류: live)\n"
        "https://x.com/medazcd/status/2081514911042031870"
    )
    assert "long post body" not in message
    assert "keyword live" not in message


def test_notification_message_uses_short_user_facing_labels() -> None:
    expected_labels = {
        "notice": "공지",
        "release": "신곡",
        "live_event": "live",
        "ticket": "티켓",
        "merch": "굿즈",
        "irrelevant": "잡담",
    }

    for item_type, label in expected_labels.items():
        message = _build_notification_message(
            source={"artist_name": "HACHI", "x_username": "8HaChi_hacchi"},
            post={"id": "1", "text": "body"},
            item_type=item_type,
            classification_reason=None,
            event=None,
        )
        assert f"(분류: {label})" in message


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
