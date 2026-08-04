from app.integrations.youtube_live_archive import _timestamp_to_seconds, parse_setlist_comment
from app.integrations.karaoke_lookup import split_song_credit


def test_parse_setlist_comment_extracts_timestamped_songs() -> None:
    comment = """
    セットリスト
    0:42 - First Song
    12:03　Second Song
    1:04:59 | Third Song
    ご視聴ありがとうございました
    """

    assert parse_setlist_comment(comment) == [
        {"timestamp": "0:42", "title": "First Song"},
        {"timestamp": "12:03", "title": "Second Song"},
        {"timestamp": "1:04:59", "title": "Third Song"},
    ]


def test_parse_setlist_comment_ignores_comment_without_timestamps() -> None:
    assert parse_setlist_comment("楽しい配信でした！") == []


def test_timestamp_to_seconds_supports_hour_timestamp() -> None:
    assert _timestamp_to_seconds("1:04:59") == 3899
    assert _timestamp_to_seconds("12:03") == 723


def test_split_song_credit_allows_missing_artist() -> None:
    assert split_song_credit("アイドル / YOASOBI") == ("アイドル", "YOASOBI")
    assert split_song_credit("名前のない歌") == ("名前のない歌", None)
