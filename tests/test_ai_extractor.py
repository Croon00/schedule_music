from pydantic import ValidationError

from app.integrations.ai_extractor import MusicEventExtraction


def test_music_event_extraction_prefers_korean_fields_and_merges_ticket_details() -> None:
    extraction = MusicEventExtraction.model_validate(
        {
            "is_live_event": True,
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
