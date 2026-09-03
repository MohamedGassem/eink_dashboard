from datetime import UTC, datetime, timedelta

from eink_dashboard.core.config import (
    DashboardConfig,
    DirectionAlias,
    DisruptionLine,
    DisruptionsConfig,
    WeatherConfig,
)
from eink_dashboard.domain.bikes import BikeStation
from eink_dashboard.domain.disruptions import TransitDisruption
from eink_dashboard.domain.transit import Departure, StopBoard
from eink_dashboard.domain.weather import WeatherSnapshot
from eink_dashboard.render.viewmodel import build_view, format_bikes, format_wait
from eink_dashboard.state import DashboardState, Store

T0 = datetime(2026, 9, 2, 8, 0, tzinfo=UTC)
STALE_AFTER = 180.0

CONFIG = DashboardConfig(
    direction_aliases=[
        DirectionAlias(match="Saint-Priest", label="St-Priest"),
        DirectionAlias(match="Hôtel de Région", label="Perrache"),
    ],
    disruptions=DisruptionsConfig(
        lines=["T2", "D"],
        line_refs=[
            DisruptionLine(label="T2", refs=["ActIV:Line::T2:SYTRAL"]),
            DisruptionLine(label="D", refs=["ActIV:Line::D:SYTRAL"]),
        ],
    ),
    weather=WeatherConfig(latitude=45.75, longitude=4.85),
)
V1_CONFIG = DashboardConfig()


def _disruption(
    source_id: str, lines: tuple[str, ...], summary: str = "Trafic perturbé", **kwargs: object
) -> TransitDisruption:
    base: dict[str, object] = {
        "valid_from": T0 - timedelta(hours=1),
        "valid_until": T0 + timedelta(hours=3),
        "severity": None,
        "planned": None,
    }
    base.update(kwargs)
    return TransitDisruption(
        source_id=source_id, lines=lines, summary=summary, description=summary, **base
    )


def store_with(
    tcl_status: str = "ok",
    velov_status: str = "ok",
    disruptions: tuple[TransitDisruption, ...] = (),
    disruptions_status: str = "ok",
    weather: WeatherSnapshot | None = None,
    weather_status: str = "ok",
) -> Store:
    store = Store()
    boards = (
        StopBoard(
            stop_name="Route de Vienne (vers St-Priest)",
            departures=(
                Departure("T2", "Saint-Priest Bel Air", T0 + timedelta(minutes=2), True),
                Departure("T2", "Saint-Priest Bel Air", T0 + timedelta(minutes=9), True),
                Departure("T2", "Saint-Priest Bel Air", T0 + timedelta(minutes=15), True),
                Departure("T2", "Saint-Priest Bel Air", T0 + timedelta(minutes=21), True),
            ),
        ),
        StopBoard(
            stop_name="Route de Vienne (vers Perrache)",
            departures=(Departure("T2", "Perrache", T0 + timedelta(minutes=4), True),),
        ),
    )
    stations = (
        BikeStation("7052", "Blandan", 0, 0, 0, 18, 20, True, T0),
        BikeStation("7023", "Berthelot", 4, 2, 2, 10, 16, True, T0),
    )
    store.record_success("tcl", boards, T0)
    store.record_success("velov", stations, T0)
    store.record_success("tcl_disruptions", disruptions, T0)
    if weather is not None:
        store.record_success("weather", weather, T0)
    if tcl_status != "ok":
        store.record_failure("tcl", "timeout", T0)
    if velov_status != "ok":
        store.record_failure("velov", "timeout", T0)
    if disruptions_status != "ok":
        store.record_failure("tcl_disruptions", "timeout", T0)
    if weather_status != "ok" and weather is not None:
        store.record_failure("weather", "timeout", T0)
    return store


def view_of(state: DashboardState, now: datetime = T0, config: DashboardConfig = CONFIG):
    return build_view(
        state,
        now,
        config,
        tcl_stale_after_seconds=STALE_AFTER,
        velov_stale_after_seconds=STALE_AFTER,
        tcl_disruptions_stale_after_seconds=STALE_AFTER,
        weather_stale_after_seconds=STALE_AFTER,
    )


# --- helpers ---------------------------------------------------------------


def test_format_wait_zero_is_a_quai() -> None:
    assert format_wait(0) == "à quai"


def test_format_wait_caps_long_waits() -> None:
    assert format_wait(75) == "+60 min"


def test_format_bikes_singular_plural_and_zero() -> None:
    assert format_bikes(0) == "0 vélo"
    assert format_bikes(1) == "1 vélo"
    assert format_bikes(4) == "4 vélos"


# --- 7.1 passages --------------------------------------------------------


def test_one_row_per_line_and_aliased_direction_without_stop_title() -> None:
    view = view_of(store_with().state)

    assert [(r.line, r.direction) for r in view.departures] == [
        ("T2", "St-Priest"),
        ("T2", "Perrache"),
    ]
    assert view.departures[0].first_wait == "2 min"
    assert view.departures[0].next_waits == ("9 min", "15 min", "21 min")
    assert view.departures[1].first_wait == "4 min"


def test_no_departure_row_when_source_is_empty() -> None:
    assert view_of(Store().state).departures == ()


# --- 7.2 Vélo'v --------------------------------------------------------


def test_bike_rows_only_carry_label_count_and_stale() -> None:
    view = view_of(store_with().state)

    assert [(b.label, b.bikes) for b in view.bikes] == [("Blandan", 0), ("Berthelot", 4)]
    assert all(b.stale is False for b in view.bikes)


def test_bike_docks_change_does_not_change_the_hash() -> None:
    base = view_of(store_with().state)
    store = store_with()
    store.state.velov.data = (
        BikeStation("7052", "Blandan", 0, 0, 0, 3, 20, True, T0),
        BikeStation("7023", "Berthelot", 4, 2, 2, 1, 16, True, T0),
    )
    assert view_of(store.state).content_hash() == base.content_hash()


def test_bike_count_change_changes_the_hash() -> None:
    base = view_of(store_with().state)
    store = store_with()
    store.state.velov.data = (
        BikeStation("7052", "Blandan", 2, 2, 0, 18, 20, True, T0),
        BikeStation("7023", "Berthelot", 4, 2, 2, 10, 16, True, T0),
    )
    assert view_of(store.state).content_hash() != base.content_hash()


# --- 7.3 perturbations --------------------------------------------------


def test_provider_ok_with_zero_disruptions_shows_nothing() -> None:
    view = view_of(store_with().state)
    assert view.alerts == ()
    assert view.traffic_note == ""


def test_provider_stale_sets_traffic_note_and_no_alerts() -> None:
    view = view_of(store_with(disruptions_status="error").state)
    assert view.alerts == ()
    assert view.traffic_note == "Info trafic indisponible"


def test_active_t2_and_d_disruptions_become_alert_rows() -> None:
    view = view_of(
        store_with(
            disruptions=(
                _disruption("A", ("T2",), "T2 : trafic perturbé"),
                _disruption("B", ("D",), "D : station non desservie"),
            )
        ).state
    )
    assert [a.line for a in view.alerts] == ["D", "T2"]


def test_single_situation_touching_t2_and_d_is_one_row() -> None:
    view = view_of(store_with(disruptions=(_disruption("A", ("D", "T2")),)).state)
    assert [a.line for a in view.alerts] == ["D/T2"]


def test_alerts_are_capped_at_two() -> None:
    view = view_of(
        store_with(
            disruptions=(
                _disruption("A", ("T2",)),
                _disruption("B", ("D",)),
                _disruption("C", ("D", "T2")),
            )
        ).state
    )
    assert len(view.alerts) == 2


def test_expired_disruption_is_dropped() -> None:
    view = view_of(
        store_with(
            disruptions=(_disruption("A", ("T2",), valid_until=T0 - timedelta(minutes=1)),)
        ).state
    )
    assert view.alerts == ()


def test_alert_text_is_truncated_at_the_safety_limit() -> None:
    view = view_of(store_with(disruptions=(_disruption("A", ("T2",), "x" * 300),)).state)
    assert len(view.alerts[0].text) <= 110


def test_disruptions_not_configured_never_shows_a_traffic_note() -> None:
    view = view_of(store_with(disruptions_status="error").state, config=V1_CONFIG)
    assert view.traffic_note == ""
    assert view.alerts == ()


# --- 7.4 météo --------------------------------------------------------


def test_weather_rounds_temperature_and_reports_rain_hour() -> None:
    view = view_of(store_with(weather=WeatherSnapshot(12.4, T0.replace(hour=15), T0)).state)
    assert view.weather is not None
    assert view.weather.temperature == "12°C"
    assert view.weather.condition == "Pluie vers 15h"


def test_weather_without_rain_says_sec() -> None:
    view = view_of(store_with(weather=WeatherSnapshot(12.4, None, T0)).state)
    assert view.weather is not None
    assert view.weather.condition == "Sec"


def test_weather_stale_says_unavailable() -> None:
    view = view_of(
        store_with(weather=WeatherSnapshot(12.4, None, T0), weather_status="error").state
    )
    assert view.weather is not None
    assert view.weather.condition == "Météo indisponible"
    assert view.weather.temperature == ""


def test_weather_not_configured_is_none() -> None:
    view = view_of(store_with().state, config=V1_CONFIG)
    assert view.weather is None


# --- 7.5 hash --------------------------------------------------------


def test_hash_ignores_the_as_of_label() -> None:
    first = view_of(store_with().state)
    later = view_of(store_with().state, T0 + timedelta(minutes=0))
    shifted = type(first)(
        as_of="23:59",
        departures=later.departures,
        bikes=later.bikes,
        alerts=later.alerts,
        weather=later.weather,
        traffic_note=later.traffic_note,
    )
    assert first.content_hash() == shifted.content_hash()


def test_new_disruption_changes_the_hash() -> None:
    base = view_of(store_with().state)
    withalert = view_of(store_with(disruptions=(_disruption("A", ("T2",)),)).state)
    assert base.content_hash() != withalert.content_hash()


def test_removing_an_expired_disruption_changes_the_hash() -> None:
    active = view_of(store_with(disruptions=(_disruption("A", ("T2",)),)).state)
    gone = view_of(
        store_with(
            disruptions=(_disruption("A", ("T2",), valid_until=T0 - timedelta(minutes=1)),)
        ).state
    )
    assert active.content_hash() != gone.content_hash()
