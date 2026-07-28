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
