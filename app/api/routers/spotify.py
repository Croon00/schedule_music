"""Spotify artist discovery, linking, discography, and relationship endpoints."""
from fastapi import APIRouter, status

from app.api import main as handlers
from app.integrations.spotify import SpotifyAlbumDetail, SpotifyAlbumSummary, SpotifyArtistProfile, SpotifyRegisteredArtist, SpotifyRelationship

router = APIRouter(tags=["spotify"])
router.add_api_route("/spotify/artists", handlers.list_spotify_artists, methods=["GET"], response_model=list[SpotifyRegisteredArtist])
router.add_api_route("/spotify/artists/{artist_id}/candidates", handlers.get_spotify_artist_candidates, methods=["GET"], response_model=list[SpotifyArtistProfile])
router.add_api_route("/spotify/artists/{artist_id}/profile", handlers.get_spotify_artist_profile, methods=["GET"], response_model=SpotifyArtistProfile)
router.add_api_route("/spotify/artists/{artist_id}/sync", handlers.sync_spotify_artist, methods=["POST"], response_model=SpotifyRegisteredArtist)
router.add_api_route("/spotify/artists/{artist_id}/youtube-auto-link", handlers.auto_link_existing_spotify_artist_youtube, methods=["POST"], response_model=SpotifyRegisteredArtist)
router.add_api_route("/spotify/artists/{artist_id}", handlers.exclude_spotify_artist, methods=["DELETE"], status_code=status.HTTP_204_NO_CONTENT)
router.add_api_route("/spotify/artists/{artist_id}/enable", handlers.enable_spotify_artist, methods=["POST"], status_code=status.HTTP_204_NO_CONTENT)
router.add_api_route("/spotify/artists/{artist_id}/discography", handlers.get_spotify_discography, methods=["GET"], response_model=list[SpotifyAlbumSummary])
router.add_api_route("/spotify/albums/{album_id}", handlers.get_spotify_album, methods=["GET"], response_model=SpotifyAlbumDetail)
router.add_api_route("/spotify/relationships", handlers.get_spotify_relationships, methods=["GET"], response_model=list[SpotifyRelationship])
