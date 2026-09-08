import pytest

from app.integrations.youtube_archive_durations import parse_duration


@pytest.mark.parametrize(("value", "expected"), [
    ("PT59S", 59), ("PT3M", 180), ("PT7M", 420), ("PT7M1S", 421),
    ("PT1H2M3S", 3723), ("P1DT2H", 93600), ("PT0S", 0),
    ("", None), ("PT", None), ("unknown", None),
])
def test_parse_duration(value, expected):
    assert parse_duration(value) == expected
