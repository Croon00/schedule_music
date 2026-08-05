from app.agents.scheduler import _normalize_live_date_from_post


def test_normalize_yearless_live_date_uses_post_year() -> None:
    extracted = {
        "is_live_event": True,
        "starts_at": "2023-07-27T18:00:00+09:00",
    }
    _normalize_live_date_from_post(
        {"created_at": "2026-07-27T05:01:00Z", "text": "7/27 18:00~ 俺召喚歌枠"},
        extracted,
    )
    assert extracted["starts_at"] == "2026-07-27T18:00:00+09:00"


def test_normalize_today_live_date_uses_post_date() -> None:
    extracted = {
        "is_live_event": True,
        "starts_at": "2023-10-11T21:00:00+09:00",
    }
    _normalize_live_date_from_post(
        {"created_at": "2026-08-03T10:59:52Z", "text": "本日21:00～歌枠！"},
        extracted,
    )
    assert extracted["starts_at"] == "2026-08-03T21:00:00+09:00"


def test_normalize_stylized_digits_in_live_date() -> None:
    extracted = {"is_live_event": True, "starts_at": "2023-07-27T18:00:00+09:00"}
    _normalize_live_date_from_post(
        {"created_at": "2026-07-27T03:00:01Z", "text": "Today 𝟕/𝟐𝟕 𝟏𝟖:𝟎𝟎～"},
        extracted,
    )
    assert extracted["starts_at"] == "2026-07-27T18:00:00+09:00"
