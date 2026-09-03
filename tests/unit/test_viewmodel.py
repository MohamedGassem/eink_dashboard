from datetime import UTC, datetime, timedelta

from eink_dashboard.domain.bikes import BikeStation
from eink_dashboard.domain.transit import Departure, StopBoard
from eink_dashboard.render.viewmodel import build_view, format_wait
from eink_dashboard.state import DashboardState, Store

T0 = datetime(2026, 9, 2, 8, 0, tzinfo=UTC)
STALE_AFTER = 180.0


def store_with(tcl_status: str = "ok", velov_status: str = "ok") -> Store:
    store = Store()
    boards = (
        StopBoard(
            stop_name="Bellecour",
            departures=(
                Departure("A", "Vaulx-en-Velin La Soie", T0 + timedelta(minutes=2), True),
                Departure("A", "Vaulx-en-Velin La Soie", T0 + timedelta(minutes=9), True),
                Departure("D", "Gare de Venissieux", T0 + timedelta(minutes=4), True),
            ),
        ),
    )
    stations = (BikeStation("1032", "Pizay", 12, 8, 4, 7, 20, True, T0),)
    store.record_success("tcl", boards, T0)
    store.record_success("velov", stations, T0)
    if tcl_status != "ok":
        store.record_failure("tcl", "timeout", T0)
    if velov_status != "ok":
        store.record_failure("velov", "timeout", T0)
    return store


def view_of(state: DashboardState, now: datetime = T0):
    return build_view(
        state,
        now,
        tcl_stale_after_seconds=STALE_AFTER,
        velov_stale_after_seconds=STALE_AFTER,
    )


def test_format_wait_zero_is_a_quai() -> None:
    assert format_wait(0) == "à quai"


def test_format_wait_uses_minutes() -> None:
    assert format_wait(3) == "3 min"


def test_format_wait_caps_long_waits() -> None:
    assert format_wait(75) == "+60 min"


def test_departures_are_grouped_by_line_and_direction() -> None:
    view = view_of(store_with().state)
    block = view.stops[0]

    assert block.title == "Bellecour"
    assert [line.line for line in block.lines] == ["A", "D"]
    assert block.lines[0].waits == ("2 min", "9 min")
    assert block.lines[1].waits == ("4 min",)


def test_bike_block_carries_counts_and_capacity() -> None:
    view = view_of(store_with().state)

    assert view.bikes[0].label == "Pizay"
    assert view.bikes[0].bikes == 12
    assert view.bikes[0].docks == 7
    assert view.bikes[0].capacity == 20


def test_stale_provider_sets_the_flag_and_a_note() -> None:
    view = view_of(store_with(tcl_status="error").state)

    assert view.stops[0].stale is True
    assert view.stops[0].note != ""
    assert view.bikes[0].stale is False


def test_empty_state_still_produces_a_view() -> None:
    view = view_of(Store().state)

    assert view.stops == ()
    assert view.bikes == ()
    assert view.as_of != ""


def test_hash_is_stable_for_identical_content() -> None:
    first = view_of(store_with().state)
    second = view_of(store_with().state)

    assert first.content_hash() == second.content_hash()


def test_hash_ignores_the_as_of_label() -> None:
    first = view_of(store_with().state)
    second = view_of(store_with().state)
    shifted = type(second)(as_of="23:59", stops=second.stops, bikes=second.bikes)

    assert first.content_hash() == shifted.content_hash()


def test_hash_changes_when_a_wait_changes() -> None:
    first = view_of(store_with().state)
    second = view_of(store_with().state, T0 + timedelta(minutes=1))

    assert first.content_hash() != second.content_hash()
