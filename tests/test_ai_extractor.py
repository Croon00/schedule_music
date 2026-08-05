from pydantic import ValidationError

from app.integrations.ai_extractor import (
    MusicEventExtraction,
    classify_source_item_by_rules,
    infer_event_format,
)


def test_music_event_extraction_prefers_korean_fields_and_merges_ticket_details() -> None:
    extraction = MusicEventExtraction.model_validate(
        {
            "is_live_event": True,
            "event_format": "onsite",
            "title": "Original title",
            "title_ko": "한국어 제목",
            "starts_at": "2026-06-10T18:00:00+09:00",
            "venue": "Original venue",
            "venue_ko": "한국어 장소",
            "ticket_opens_at": "2026-05-01T12:00:00+09:00",
            "ticket_closes_at": None,
            "ticket_url": "https://example.com/tickets",
            "price_text": "S석: 12,000엔",
            "ticket_details_ko": "응모 기간: 5월 1일 12:00부터",
            "confidence": 0.9,
        }
    )

    event = extraction.to_event_candidate()

    assert event is not None
    assert event["title"] == "한국어 제목"
    assert event["venue"] == "한국어 장소"
    assert event["price_text"] == "S석: 12,000엔\n\n응모 기간: 5월 1일 12:00부터"


def test_music_event_extraction_filters_low_confidence() -> None:
    extraction = MusicEventExtraction.model_validate(
        {
            "is_live_event": True,
            "event_format": "unknown",
            "title": "Live",
            "title_ko": None,
            "starts_at": None,
            "venue": None,
            "venue_ko": None,
            "ticket_opens_at": None,
            "ticket_closes_at": None,
            "ticket_url": None,
            "price_text": None,
            "ticket_details_ko": None,
            "confidence": 0.2,
        }
    )

    assert extraction.to_event_candidate() is None


def test_music_event_extraction_rejects_extra_fields() -> None:
    try:
        MusicEventExtraction.model_validate(
            {
                "is_live_event": True,
                "event_format": "onsite",
                "title": "Live",
                "title_ko": None,
                "starts_at": None,
                "venue": None,
                "venue_ko": None,
                "ticket_opens_at": None,
                "ticket_closes_at": None,
                "ticket_url": None,
                "price_text": None,
                "ticket_details_ko": None,
                "confidence": 0.9,
                "unexpected": "nope",
            }
        )
    except ValidationError:
        return

    raise AssertionError("extra fields should be rejected")


def test_rule_classifier_prioritizes_ticket_over_live_event() -> None:
    classification = classify_source_item_by_rules(
        "2nd ONE-MAN LIVE チケット先行受付開始のお知らせ"
    )

    assert classification.item_type == "ticket"
    assert classification.confidence > 0


def test_rule_classifier_detects_release_posts() -> None:
    classification = classify_source_item_by_rules(
        "新曲 Digital Single 配信開始 / Music Video 公開"
    )

    assert classification.item_type == "release"


def test_rule_classifier_marks_chatter_irrelevant() -> None:
    classification = classify_source_item_by_rules("おはようございます。今日もよろしくお願いします。")

    assert classification.item_type == "irrelevant"


def test_event_format_detects_online_youtube_live() -> None:
    assert infer_event_format(
        raw_text="今夜はYouTube Liveで歌枠を配信します",
        ticket_url="https://youtube.com/live/example",
    ) == "online"


def test_event_format_does_not_treat_online_venue_as_physical() -> None:
    assert infer_event_format(
        raw_text="本日21:00から歌枠",
        venue="온라인 (YouTube 라이브)",
        ticket_url="https://youtube.com/live/example",
    ) == "online"


def test_event_format_detects_physical_venue() -> None:
    assert infer_event_format(
        raw_text="Zepp Shinjuku 開場 17:00 / 開演 18:00",
        venue="Zepp Shinjuku",
        ticket_url="https://youtu.be/trailer",
    ) == "onsite"


def test_event_format_detects_hybrid_event() -> None:
    assert infer_event_format(
        raw_text="会場公演をYouTube Liveでも生配信します",
        venue="東京ホール",
    ) == "hybrid"
