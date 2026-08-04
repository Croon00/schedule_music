import pytest

from app.integrations.youtube_channel_monitor import _channel_locator


def test_channel_locator_supports_handle_and_channel_id_urls() -> None:
    assert _channel_locator("https://www.youtube.com/@HACHIVSinger") == (
        "handle", "HACHIVSinger"
    )
    assert _channel_locator(
        "https://www.youtube.com/channel/UCaaaaaaaaaaaaaaaaaaaaaa"
    ) == ("id", "UCaaaaaaaaaaaaaaaaaaaaaa")


def test_channel_locator_rejects_video_and_custom_urls() -> None:
    with pytest.raises(ValueError):
        _channel_locator("https://www.youtube.com/watch?v=abcdefghijk")
