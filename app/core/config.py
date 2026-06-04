from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Railway와 로컬 .env에서 읽어오는 앱 전체 설정입니다."""

    app_name: str = "schedule-music"
    database_url: str
    discord_bot_token: str | None = None
    discord_guild_id: int | None = None
    agent_interval_seconds: int = 300
    public_base_url: str | None = None
    x_bearer_token: str | None = None
    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1-mini"
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str | None = None
    google_calendar_id: str = "primary"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @field_validator(
        "discord_bot_token",
        "discord_guild_id",
        "public_base_url",
        "x_bearer_token",
        "openai_api_key",
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
