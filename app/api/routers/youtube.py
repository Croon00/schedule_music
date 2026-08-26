"""YouTube live archive and performance endpoints."""
from fastapi import APIRouter, status

from app.api import main as handlers

router = APIRouter(tags=["youtube"])
router.add_api_route("/youtube-lives", handlers.create_youtube_live, methods=["POST"], status_code=status.HTTP_201_CREATED)
router.add_api_route("/youtube-lives/backfills", handlers.create_youtube_live_backfill, methods=["POST"], status_code=status.HTTP_202_ACCEPTED)
router.add_api_route("/youtube-lives", handlers.get_youtube_lives, methods=["GET"])
router.add_api_route("/youtube-lives/{archive_id}", handlers.get_youtube_live, methods=["GET"])
router.add_api_route("/youtube-performances", handlers.search_youtube_performances, methods=["GET"])
router.add_api_route("/youtube-performance-filters", handlers.get_youtube_performance_filters, methods=["GET"])
router.add_api_route("/youtube-performances/{performance_id}", handlers.patch_youtube_performance, methods=["PATCH"])
