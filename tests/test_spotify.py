from app.integrations.spotify import spotify_track_from_api_item


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
