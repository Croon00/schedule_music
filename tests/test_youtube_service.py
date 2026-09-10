from unittest.mock import patch

from app.services.youtube_service import YouTubeService


def test_all_artist_records_are_not_capped_at_100():
    rows = [{"id": i} for i in range(267)]
    with patch('app.services.youtube_service.list_youtube_live_archives', return_value=rows) as query:
        assert len(YouTubeService().list_lives(100, 'HACHI', all_records=True)) == 267
        query.assert_called_once_with(limit=None, artist_name='HACHI')


def test_global_requests_remain_bounded():
    with patch('app.services.youtube_service.list_youtube_live_archives', return_value=[]) as query:
        YouTubeService().list_lives(500, None, all_records=True)
        query.assert_called_once_with(limit=100, artist_name=None)
