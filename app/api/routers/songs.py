"""Song lyrics and Spotify-to-YouTube linking endpoints."""
from fastapi import APIRouter, status

from app.api import main as handlers
from app.core.models import SongLyricsDetail, SongLyricsSummary, WebSongCreated

router = APIRouter(tags=["songs"])
router.add_api_route("/songs/from-youtube", handlers.create_song_from_youtube, methods=["POST"], response_model=WebSongCreated, status_code=status.HTTP_201_CREATED)
router.add_api_route("/songs/lyrics/by-spotify-tracks", handlers.list_song_lyrics_by_spotify_tracks, methods=["GET"], response_model=list[SongLyricsSummary])
router.add_api_route("/songs/spotify-track-youtube", handlers.link_spotify_track_to_youtube, methods=["POST"], response_model=SongLyricsSummary)
router.add_api_route("/songs/{song_id}/credits", handlers.update_song_credits, methods=["PATCH"], response_model=SongLyricsSummary)
router.add_api_route("/songs/{song_id}/lyrics", handlers.get_song_lyrics, methods=["GET"], response_model=SongLyricsDetail)
