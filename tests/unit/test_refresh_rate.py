from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from eink_dashboard.render.viewmodel import AlertRow, BikeRow, DashboardView
from eink_dashboard.services.dashboard import (
    DAY_EVENT_REFRESH,
    DAY_IDLE_REFRESH,
    NIGHT_MAX_SLEEP,
    PEAK_REFRESH,
    refresh_rate_for,
    view_has_event,
)

PARIS = ZoneInfo("Europe/Paris")


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, 2, hour, minute, tzinfo=PARIS)


def _view(
    *,
    bikes: tuple[BikeRow, ...] = (),
    alerts: tuple[AlertRow, ...] = (),
    traffic_note: str = "",
) -> DashboardView:
    return DashboardView(
        as_of="12:00",
        departures=(),
        bikes=bikes,
        alerts=alerts,
        weather=None,
        traffic_note=traffic_note,
    )


# --- refresh_rate_for -----------------------------------------------------


@pytest.mark.parametrize("hour,minute", [(7, 30), (8, 0), (8, 59)])
def test_morning_peak_refreshes_every_three_minutes(hour: int, minute: int) -> None:
    assert refresh_rate_for(at(hour, minute)) == PEAK_REFRESH


@pytest.mark.parametrize("hour,minute", [(9, 0), (12, 0), (20, 59)])
def test_daytime_without_an_event_uses_the_long_interval(hour: int, minute: int) -> None:
    assert refresh_rate_for(at(hour, minute), has_event=False) == DAY_IDLE_REFRESH


@pytest.mark.parametrize("hour,minute", [(9, 0), (14, 30), (20, 59)])
def test_daytime_with_an_event_uses_the_short_interval(hour: int, minute: int) -> None:
    assert refresh_rate_for(at(hour, minute), has_event=True) == DAY_EVENT_REFRESH


@pytest.mark.parametrize("hour,minute", [(21, 0), (23, 30), (2, 0), (6, 0)])
def test_night_sleeps_at_most_until_the_failsafe_cap(hour: int, minute: int) -> None:
    rate = refresh_rate_for(at(hour, minute))
    assert 0 < rate <= NIGHT_MAX_SLEEP


def test_night_close_to_the_morning_start_sleeps_just_that_long() -> None:
    assert refresh_rate_for(at(7, 29)) == 60


def test_seven_thirty_exactly_is_already_the_morning_peak() -> None:
    assert refresh_rate_for(at(7, 30)) == PEAK_REFRESH


def test_nine_pm_exactly_is_night() -> None:
    assert refresh_rate_for(at(21, 0)) > DAY_IDLE_REFRESH


# --- view_has_event -----------------------------------------------------


def test_event_when_a_station_is_below_the_threshold() -> None:
    assert view_has_event(_view(bikes=(BikeRow("Blandan", 2, False),))) is True


def test_event_when_a_station_is_stale() -> None:
    assert view_has_event(_view(bikes=(BikeRow("Blandan", 9, True),))) is True


def test_event_on_an_active_alert() -> None:
    assert view_has_event(_view(alerts=(AlertRow("T2", "trafic perturbé"),))) is True


def test_event_when_disruptions_are_unavailable() -> None:
    assert view_has_event(_view(traffic_note="Info trafic indisponible")) is True


def test_no_event_when_everything_is_calm() -> None:
    assert view_has_event(_view(bikes=(BikeRow("Blandan", 9, False),))) is False
