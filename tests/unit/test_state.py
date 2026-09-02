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


def test_new_store_reports_unknown() -> None:
    store = Store()
    assert store.state.tcl.status == "unknown"
    assert store.state.tcl.data is None
    assert store.state.velov.status == "unknown"


def test_record_success_sets_ok_and_timestamp() -> None:
    store = Store()
    store.record_success("tcl", board(), T0)

    assert store.state.tcl.status == "ok"
    assert store.state.tcl.updated_at == T0
    assert store.state.tcl.data is not None
    assert store.state.tcl.error is None


def test_record_failure_keeps_last_good_data() -> None:
    store = Store()
    store.record_success("tcl", board(), T0)
    store.record_failure("tcl", "timeout", T0 + timedelta(seconds=60))

    assert store.state.tcl.status == "error"
    assert store.state.tcl.error == "timeout"
    assert store.state.tcl.data is not None
    assert store.state.tcl.updated_at == T0


def test_failure_on_one_provider_leaves_the_other_untouched() -> None:
    store = Store()
    store.record_success("tcl", board(), T0)
    store.record_success("velov", station(), T0)
    store.record_failure("tcl", "boom", T0 + timedelta(seconds=60))

    assert store.state.tcl.status == "error"
    assert store.state.velov.status == "ok"


def test_mark_stale_if_old_flips_ok_to_stale() -> None:
    store = Store()
    store.record_success("velov", station(), T0)
    store.mark_stale_if_old(T0 + timedelta(seconds=181), max_age_seconds=180)

    assert store.state.velov.status == "stale"


def test_mark_stale_if_old_leaves_fresh_data_alone() -> None:
    store = Store()
    store.record_success("velov", station(), T0)
    store.mark_stale_if_old(T0 + timedelta(seconds=100), max_age_seconds=180)

    assert store.state.velov.status == "ok"


def test_age_seconds_is_none_without_data() -> None:
    store = Store()
    assert store.state.tcl.age_seconds(T0) is None
