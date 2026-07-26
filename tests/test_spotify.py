from app.integrations.spotify import (
    spotify_album_from_api_item,
    spotify_artist_from_api_item,
    spotify_track_from_api_item,
)


def test_spotify_track_from_api_item_extracts_core_metadata() -> None:
    track = spotify_track_from_api_item(
        {
            "id": "track123",
            "name": "Song Title",
            "duration_ms": 210000,
            "external_urls": {"spotify": "https://open.spotify.com/track/track123"},
            "artists": [
                {"id": "artist1", "name": "Artist One"},
                {"id": "artist2", "name": "Artist Two"},
            ],
            "album": {
                "id": "album123",
                "name": "Album Title",
                "release_date": "2026-07-03",
                "images": [
                    {"url": "https://i.scdn.co/image/large", "height": 640, "width": 640}
                ],
            },
        }
    )

    assert track.track_id == "track123"
    assert track.name == "Song Title"
    assert track.artists == ["Artist One", "Artist Two"]
    assert track.artist_ids == ["artist1", "artist2"]
    assert track.album_id == "album123"
    assert track.album_name == "Album Title"
    assert track.release_date == "2026-07-03"
    assert track.duration_ms == 210000
    assert track.spotify_url == "https://open.spotify.com/track/track123"
    assert track.cover_image_url == "https://i.scdn.co/image/large"


def test_spotify_artist_and_album_metadata_are_parsed() -> None:
    artist = spotify_artist_from_api_item(
        7,
        {
            "id": "artist123",
            "name": "HACHI",
            "images": [{"url": "https://i.scdn.co/image/artist"}],
            "external_urls": {"spotify": "https://open.spotify.com/artist/artist123"},
            "genres": ["virtual singer"],
        },
    )
    album = spotify_album_from_api_item(
        {
            "id": "album123",
            "name": "Midnight Blue",
            "album_type": "single",
            "release_date": "2026-07-23",
            "release_date_precision": "day",
            "total_tracks": 1,
            "images": [{"url": "https://i.scdn.co/image/album"}],
            "external_urls": {"spotify": "https://open.spotify.com/album/album123"},
            "artists": [{"id": "artist123", "name": "HACHI"}],
        },
    )

    assert artist.local_artist_id == 7
    assert artist.image_url == "https://i.scdn.co/image/artist"
    assert album.album_type == "single"
    assert album.artist_ids == ["artist123"]
