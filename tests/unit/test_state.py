from datetime import UTC, datetime, timedelta

from eink_dashboard.domain.bikes import BikeStation
from eink_dashboard.domain.transit import Departure, StopBoard
from eink_dashboard.state import Store

T0 = datetime(2026, 9, 2, 8, 0, tzinfo=UTC)


def board() -> tuple[StopBoard, ...]:
    return (
        StopBoard(
            stop_name="Bellecour",
            departures=(Departure("A", "Vaulx", T0 + timedelta(minutes=3), is_realtime=True),),
        ),
    )


def station() -> tuple[BikeStation, ...]:
    return (BikeStation("1032", "Pizay", 12, 8, 4, 8, 20, True, T0),)


def test_departure_minutes_until_rounds_down() -> None:
    departure = Departure("A", "Vaulx", T0 + timedelta(seconds=209), is_realtime=True)
    assert departure.minutes_until(T0) == 3


def test_departure_minutes_until_never_negative() -> None:
    departure = Departure("A", "Vaulx", T0 - timedelta(minutes=5), is_realtime=True)
    assert departure.minutes_until(T0) == 0


def test_stop_board_distinguishes_no_departure_from_unavailable() -> None:
    no_departure = StopBoard(stop_name="Bellecour", departures=())
    unavailable = StopBoard(stop_name="Part-Dieu", departures=(), available=False)

    assert no_departure.available is True
    assert unavailable.available is False


def test_new_store_reports_unavailable() -> None:
    store = Store()
    assert store.state.tcl.status_at(T0, stale_after_seconds=180) == "unavailable"
    assert store.state.tcl.data is None
    assert store.state.velov.status_at(T0, stale_after_seconds=180) == "unavailable"


def test_record_success_sets_ok_and_timestamp() -> None:
    store = Store()
    store.record_success("tcl", board(), T0)

    assert store.state.tcl.status_at(T0, stale_after_seconds=180) == "ok"
    assert store.state.tcl.last_attempt_at == T0
    assert store.state.tcl.last_success_at == T0
    assert store.state.tcl.source_updated_at is None
    assert store.state.tcl.data is not None
    assert store.state.tcl.last_error is None


def test_record_failure_keeps_last_good_data() -> None:
    store = Store()
    store.record_success("tcl", board(), T0)
    store.record_failure("tcl", "timeout", T0 + timedelta(seconds=60))

    assert (
        store.state.tcl.status_at(T0 + timedelta(seconds=60), stale_after_seconds=180) == "degraded"
    )
    assert store.state.tcl.last_error == "timeout"
    assert store.state.tcl.last_attempt_at == T0 + timedelta(seconds=60)
    assert store.state.tcl.data is not None
    assert store.state.tcl.last_success_at == T0


def test_failure_on_one_provider_leaves_the_other_untouched() -> None:
    store = Store()
    store.record_success("tcl", board(), T0)
    store.record_success("velov", station(), T0)
    store.record_failure("tcl", "boom", T0 + timedelta(seconds=60))

    now = T0 + timedelta(seconds=60)
    assert store.state.tcl.status_at(now, stale_after_seconds=180) == "degraded"
    assert store.state.velov.status_at(now, stale_after_seconds=180) == "ok"


def test_old_last_good_is_stale_even_after_a_fetch_failure() -> None:
    store = Store()
    store.record_success("velov", station(), T0)
    store.record_failure("velov", "timeout", T0 + timedelta(seconds=60))

    assert (
        store.state.velov.status_at(T0 + timedelta(seconds=181), stale_after_seconds=180) == "stale"
    )


def test_each_provider_uses_its_own_freshness_threshold() -> None:
    store = Store()
    store.record_success("tcl", board(), T0)
    store.record_success("velov", station(), T0)
    now = T0 + timedelta(seconds=181)

    assert store.state.tcl.status_at(now, stale_after_seconds=180) == "stale"
    assert store.state.velov.status_at(now, stale_after_seconds=600) == "ok"


def test_source_timestamp_drives_freshness_when_available() -> None:
    store = Store()
    source_time = T0 - timedelta(hours=2)
    store.record_success("velov", station(), T0, source_updated_at=source_time)

    assert store.state.velov.last_success_at == T0
    assert store.state.velov.source_updated_at == source_time
    assert store.state.velov.age_seconds(T0) == 7200
    assert store.state.velov.status_at(T0, stale_after_seconds=180) == "stale"


def test_age_seconds_is_none_without_data() -> None:
    store = Store()
    assert store.state.tcl.age_seconds(T0) is None
