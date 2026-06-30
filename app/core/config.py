from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Railway와 로컬 .env에서 읽어오는 앱 전체 설정입니다."""

    app_name: str = "schedule-music"
    database_url: str | None = None
    discord_bot_token: str | None = None
    discord_guild_id: int | None = None
    agent_interval_seconds: int = 86400
    agent_enabled: bool = True
    agent_run_on_start: bool = True
    database_auto_init: bool = True
    public_base_url: str | None = None
    x_bearer_token: str | None = None
    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1-mini"
    openai_audio_model: str = "whisper-1"
    lyrics_audio_fallback_max_seconds: int = 500
    youtube_transcript_proxy_http_url: str | None = None
    youtube_transcript_proxy_https_url: str | None = None
    webshare_proxy_username: str | None = None
    webshare_proxy_password: str | None = None
    webshare_proxy_locations: str | None = None
    ytdlp_proxy_url: str | None = None
    youtube_api_key: str | None = None
    lyrics_context_extract_max_chars: int = 1000
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str | None = None
    google_calendar_id: str = "primary"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @field_validator(
        "discord_bot_token",
        "database_url",
        "discord_guild_id",
        "public_base_url",
        "x_bearer_token",
        "openai_api_key",
        "youtube_transcript_proxy_http_url",
        "youtube_transcript_proxy_https_url",
        "webshare_proxy_username",
        "webshare_proxy_password",
        "webshare_proxy_locations",
        "ytdlp_proxy_url",
        "youtube_api_key",
        "google_client_id",
        "google_client_secret",
        "google_redirect_uri",
        mode="before",
    )
    @classmethod
    def empty_string_to_none(cls, value):
        """Railway/.env의 빈 문자열 값을 Optional 필드에서 None처럼 다루게 합니다."""
        if value == "":
            return None
        return value


settings = Settings()
