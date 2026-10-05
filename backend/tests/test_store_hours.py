from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.locations.router import is_open
from app.profiles.schemas import HoursInput, StoreInput


def week(**changes):
    hours = [{"day_of_week": day, "is_closed": True} for day in range(7)]
    hours[0] = {"day_of_week": 0, "open_time": "09:00", "close_time": "18:00", **changes}
    return hours


def validate(hours):
    return StoreInput(name="Branch", address="Main Street", city="Kochi", hours=hours)


@pytest.mark.parametrize(
    "hours",
    [
        week(close_time="08:00"),
        week(close_time="09:00"),
        week(open_time="25:00"),
        week(is_closed=True),
        week(closes_next_day=True, close_time="20:00"),
        week()[:6],
        week() + [week()[0]],
    ],
)
def test_invalid_hours_rejected(hours):
    with pytest.raises(ValidationError):
        validate(hours)


def test_sunday_to_monday_overlap_rejected():
    hours = week(open_time="01:00", close_time="18:00")
    hours[6] = {
        "day_of_week": 6,
        "open_time": "20:00",
        "close_time": "02:00",
        "closes_next_day": True,
    }
    with pytest.raises(ValidationError):
        validate(hours)
    hours[0]["open_time"] = "02:00"
    validate(hours)


@pytest.mark.parametrize(
    "clock,expected",
    [
        ("2026-09-28T03:29:00+00:00", False),
        ("2026-09-28T03:30:00+00:00", True),
        ("2026-09-28T12:29:00+00:00", True),
        ("2026-09-28T12:30:00+00:00", False),
    ],
)
def test_local_open_close_boundaries(clock, expected):
    assert (
        is_open(validate(week()).hours, "Asia/Kolkata", datetime.fromisoformat(clock)) is expected
    )


def test_overnight_hours_week_wrap_and_unknown_hours():
    hours = week()
    hours[6] = {
        "day_of_week": 6,
        "open_time": "20:00",
        "close_time": "02:00",
        "closes_next_day": True,
    }
    validated = validate(hours).hours
    assert is_open(validated, "Asia/Kolkata", datetime(2026, 9, 27, 20, 0, tzinfo=UTC)) is True
    assert is_open(validated, "Asia/Kolkata", datetime(2026, 9, 27, 20, 30, tzinfo=UTC)) is False
    assert is_open([], "Asia/Kolkata", datetime.now(UTC)) is None


def test_dst_repeated_hour_uses_store_wall_clock():
    hours = [HoursInput(day_of_week=6, open_time="01:00", close_time="02:00")]
    for utc_hour in (5, 6):
        assert (
            is_open(hours, "America/New_York", datetime(2026, 11, 1, utc_hour, 30, tzinfo=UTC))
            is True
        )
    assert is_open(hours, "America/New_York", datetime(2026, 11, 1, 7, 0, tzinfo=UTC)) is False
