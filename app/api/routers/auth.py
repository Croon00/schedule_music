"""Public OAuth entry and callback endpoints."""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.api import main as handlers

router = APIRouter(tags=["auth"])
router.add_api_route("/auth/google/start", handlers.start_google_auth, methods=["GET"])
router.add_api_route("/auth/google/callback", handlers.google_auth_callback, methods=["GET"], response_class=HTMLResponse)
