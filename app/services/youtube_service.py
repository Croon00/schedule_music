"""YouTube 라이브 아카이브 유스케이스를 제공한다."""

from typing import Any

from app.integrations.youtube_channel_monitor import backfill_youtube_channel
from app.integrations.youtube_live_archive import (
    add_youtube_live_url,
    ensure_youtube_live_korean_labels,
    get_youtube_live_archive,
    list_youtube_live_archives,
    list_youtube_performance_filters,
    search_youtube_song_performances,
    update_youtube_song_performance,
)


class YouTubeService:
    """YouTube 수집 연동을 API 유스케이스로 감싼다."""

    async def create_live(self, youtube_url: str, artist_name: str) -> dict[str, Any] | None:
        """YouTube 라이브 URL을 저장하고 세트리스트 수집을 시도한다."""
        archive_id = await add_youtube_live_url(youtube_url, artist_name)
        return get_youtube_live_archive(archive_id)

    def backfill_channel(self, channel_url: str, artist_name: str) -> None:
        """채널의 과거 라이브를 수집한다."""
        backfill_youtube_channel(channel_url, artist_name)

    def list_lives(self, limit: int, artist_name: str | None) -> list[dict[str, Any]]:
        """저장된 YouTube 라이브 목록을 조회한다."""
        return list_youtube_live_archives(limit=max(1, min(limit, 100)), artist_name=artist_name.strip() if artist_name else None)

    async def get_live(self, archive_id: int) -> dict[str, Any] | None:
        """한국어 메타데이터를 보완한 라이브 상세 정보를 조회한다."""
        await ensure_youtube_live_korean_labels(archive_id)
        return get_youtube_live_archive(archive_id)

    def search_performances(self, **filters: Any) -> list[dict[str, Any]]:
        """곡명·가수명 조건으로 라이브 공연 기록을 검색한다."""
        return search_youtube_song_performances(**filters)

    def list_performance_filters(self) -> dict[str, list[str]]:
        """공연 검색 필터 후보를 반환한다."""
        return list_youtube_performance_filters()

    def update_performance(self, performance_id: int, values: dict[str, str | None]) -> dict[str, Any] | None:
        """공연 곡 정보를 수정한다."""
        return update_youtube_song_performance(performance_id, values)
