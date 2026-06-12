from app.integrations.google_calendar import _to_google_event, _to_ticket_google_event


def test_to_google_event_uses_all_day_payload_for_date_only_start() -> None:
    payload = _to_google_event(
        {
            "title": "All day live",
            "starts_at": "2026-06-27",
            "venue": "Virtual",
            "source_url": "https://example.com",
            "raw_text": "raw",
        }
    )

    assert payload["start"] == {"date": "2026-06-27"}
    assert payload["end"] == {"date": "2026-06-28"}


def test_to_google_event_uses_datetime_payload_for_timestamp_start() -> None:
    payload = _to_google_event(
        {
            "title": "Timed live",
            "starts_at": "2026-06-10T18:00:00+09:00",
        }
    )

    assert payload["start"] == {"dateTime": "2026-06-10T18:00:00+09:00"}
    assert payload["end"] == {"dateTime": "2026-06-10T20:00:00+09:00"}


def test_to_ticket_google_event_uses_ticket_period_and_details() -> None:
    payload = _to_ticket_google_event(
        {
            "title": "카미츠바키 페스 2026",
            "ticket_opens_at": "2026-06-10T18:00:00+09:00",
            "ticket_closes_at": "2026-06-22T23:59:00+09:00",
            "ticket_url": "https://example.com/tickets",
            "price_text": "S석: 12,000엔\nA석: 9,000엔",
            "source_url": "https://x.com/kamitsubaki_jp/status/1",
        }
    )

    assert payload["summary"] == "티켓/응모 기간: 카미츠바키 페스 2026"
    assert payload["start"] == {"dateTime": "2026-06-10T18:00:00+09:00"}
    assert payload["end"] == {"dateTime": "2026-06-22T23:59:00+09:00"}
    assert "S석: 12,000엔" in payload["description"]
    assert "https://example.com/tickets" in payload["description"]
