"""YouTube 라이브 API 요청 모델이다."""

from pydantic import BaseModel, HttpUrl


class YouTubeLiveCreate(BaseModel):
    """YouTube 라이브 등록 요청이다."""

    youtube_url: HttpUrl
    artist_name: str


class YouTubeChannelBackfillCreate(BaseModel):
    """YouTube 채널 과거 수집 요청이다."""

    channel_url: HttpUrl
    artist_name: str
