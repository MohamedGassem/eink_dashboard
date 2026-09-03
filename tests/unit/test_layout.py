import pytest

from eink_dashboard.render.images import ImageCache, to_bmp_bytes
from eink_dashboard.render.layout import HEIGHT, WIDTH, render
from eink_dashboard.render.viewmodel import (
    AlertRow,
    BikeRow,
    DashboardView,
    DepartureRow,
    WeatherRow,
)

NOMINAL_DEPARTURES = (
    DepartureRow("T2", "St-Priest", "2 min", ("9 min", "15 min", "21 min")),
    DepartureRow("T2", "Perrache", "4 min", ("12 min", "20 min")),
)
NOMINAL_BIKES = (BikeRow("Blandan", 1, False), BikeRow("Berthelot", 4, False))


def make_view(**overrides: object) -> DashboardView:
    base: dict[str, object] = {
        "as_of": "09:54",
        "departures": NOMINAL_DEPARTURES,
        "bikes": NOMINAL_BIKES,
        "alerts": (),
        "weather": WeatherRow("12°C", "Sec"),
        "traffic_note": "",
    }
    base.update(overrides)
    return DashboardView(**base)  # type: ignore[arg-type]


SCENARIOS = {
    "nominal": make_view(),
    "t2_disruption": make_view(alerts=(AlertRow("T2", "trafic perturbé — Jean Macé ↔ Perrache"),)),
    "d_disruption": make_view(alerts=(AlertRow("D", "station non desservie — Guillotière"),)),
    "t2_and_d": make_view(
        alerts=(
            AlertRow("T2", "trafic perturbé — Jean Macé ↔ Perrache"),
            AlertRow("D", "station non desservie — Guillotière"),
        )
    ),
    "traffic_unavailable": make_view(traffic_note="Info trafic indisponible"),
    "weather_unavailable": make_view(weather=WeatherRow("", "Météo indisponible")),
    "zero_bikes": make_view(bikes=(BikeRow("Blandan", 0, False), BikeRow("Berthelot", 0, False))),
    "long_station_label": make_view(
        bikes=(BikeRow("Parc Blandan / Route de Vienne / Berthelot", 2, False),)
    ),
    "long_direction": make_view(
        departures=(DepartureRow("T2", "Saint-Priest Bel Air Parc Technologique" * 2, "3 min", ()),)
    ),
    "four_waits": make_view(
        departures=(DepartureRow("T2", "St-Priest", "2 min", ("8 min", "14 min", "20 min")),)
    ),
    "no_tcl_data": make_view(departures=()),
    "long_alert_takes_whole_zone": make_view(
        alerts=(
            AlertRow("T2", "Perturbation " * 30),
            AlertRow("D", "Deuxième alerte qui doit être omise"),
        )
    ),
    "empty": DashboardView(
        as_of="09:54", departures=(), bikes=(), alerts=(), weather=None, traffic_note=""
    ),
}


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_every_scenario_renders_a_full_frame(name: str) -> None:
    image = render(SCENARIOS[name])

    assert image.size == (WIDTH, HEIGHT)
    assert image.mode == "1"


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_every_scenario_is_deterministic(name: str) -> None:
    assert to_bmp_bytes(render(SCENARIOS[name])) == to_bmp_bytes(render(SCENARIOS[name]))


def test_distinct_scenarios_produce_distinct_frames() -> None:
    rendered = {name: to_bmp_bytes(render(view)) for name, view in SCENARIOS.items()}
    assert len(set(rendered.values())) == len(rendered)


def test_bmp_output_is_one_bit_per_pixel() -> None:
    payload = to_bmp_bytes(render(SCENARIOS["nominal"]))

    assert payload[:2] == b"BM"
    assert int.from_bytes(payload[28:30], "little") == 1


def test_image_cache_evicts_the_oldest_entry() -> None:
    cache = ImageCache(max_entries=2)
    cache.put("a", b"1")
    cache.put("b", b"2")
    cache.put("c", b"3")

    assert cache.get("a") is None
    assert cache.get("c") == b"3"
