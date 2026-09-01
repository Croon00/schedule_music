from app.integrations.jpop_playlist_tj import PlaylistSong, normalize_karaoke_text, parse_playlist_songs


def test_parse_playlist_songs_reads_tj_and_artist_columns() -> None:
    html = """
    <table><tr><th>title</th><th>TJ</th></tr>
    <tr><td>Song Name<br>translated</td><td>12345</td><td>-</td><td>Artist Name<br>artist translated</td></tr>
    <tr><td>Not registered</td><td>-</td><td>-</td><td>Artist</td></tr></table>
    """

    assert parse_playlist_songs(html, "https://example.test/post") == [
        PlaylistSong("Song Name", "Artist Name", "12345", "https://example.test/post")
    ]


def test_normalize_karaoke_text_only_removes_presentation_differences() -> None:
    assert normalize_karaoke_text(" A\u3000Song - Name! ") == "asongname"


def test_parse_playlist_songs_does_not_mistake_joysound_for_an_artist() -> None:
    html = "<table><tr><td>Song</td><td>12345</td><td>-</td><td>678901</td></tr></table>"

    assert parse_playlist_songs(html, "https://example.test/post") == [
        PlaylistSong("Song", None, "12345", "https://example.test/post")
    ]
