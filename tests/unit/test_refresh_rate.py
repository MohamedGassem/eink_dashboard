from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from eink_dashboard.services.dashboard import (
    DAY_REFRESH,
    NIGHT_REFRESH,
    PEAK_REFRESH,
    refresh_rate_for,
)

PARIS = ZoneInfo("Europe/Paris")


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, 2, hour, minute, tzinfo=PARIS)


@pytest.mark.parametrize("hour,minute", [(7, 0), (8, 30), (9, 29), (17, 0), (19, 29)])
def test_peak_hours_use_the_short_interval(hour: int, minute: int) -> None:
    assert refresh_rate_for(at(hour, minute)) == PEAK_REFRESH


@pytest.mark.parametrize("hour,minute", [(9, 30), (12, 0), (16, 59), (19, 30), (22, 59)])
def test_daytime_uses_the_medium_interval(hour: int, minute: int) -> None:
    assert refresh_rate_for(at(hour, minute)) == DAY_REFRESH


@pytest.mark.parametrize("hour,minute", [(23, 0), (2, 0), (5, 59)])
def test_night_uses_the_long_interval(hour: int, minute: int) -> None:
    assert refresh_rate_for(at(hour, minute)) == NIGHT_REFRESH


def test_six_in_the_morning_is_daytime() -> None:
    assert refresh_rate_for(at(6, 0)) == DAY_REFRESH
