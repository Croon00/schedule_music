import pytest

from app.integrations.youtube_channel_monitor import (
    _channel_locator,
    _performer_for_singing_stream,
)


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


def test_vesperbell_singing_streams_are_attributed_by_member_credit() -> None:
    assert _performer_for_singing_stream(
        "VESPERBELL", "【歌枠】title【VESPERBELL ヨミ】"
    ) == "VESPERBELL YOMI"
    assert _performer_for_singing_stream(
        "VESPERBELL", "【歌枠】title【VESPERBELL カスカ】"
    ) == "VESPERBELL KASUKA"
    assert _performer_for_singing_stream(
        "VESPERBELL", "【歌枠】title【#ヨミネロ】"
    ) == "VESPERBELL YOMI"
    assert _performer_for_singing_stream(
        "VESPERBELL", "【歌枠】title【#カスカコラボ】"
    ) == "VESPERBELL KASUKA"
    assert _performer_for_singing_stream("VESPERBELL", "【歌枠】duo stream") == "VESPERBELL"
    assert _performer_for_singing_stream("Enma_Ruri", "【歌枠】anything ヨミ") == "Enma_Ruri"


def test_kmnz_singing_streams_are_attributed_by_member_hashtag() -> None:
    assert _performer_for_singing_stream("KMNZ", "【歌枠】title #KMNZLITA") == "KMNZ LITA"
    assert _performer_for_singing_stream("KMNZ", "【歌枠】title【#KMNZNERO】") == "KMNZ NERO"
    assert _performer_for_singing_stream("KMNZ", "【歌枠】title #KMNZTINA") == "KMNZ TINA"
    assert _performer_for_singing_stream("KMNZ", "【歌枠】group stream #KMNZ") == "KMNZ"
