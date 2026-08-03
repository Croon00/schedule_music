from app.integrations.youtube_live_archive import parse_setlist_comment


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
