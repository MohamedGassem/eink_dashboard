from eink_dashboard.render.images import ImageCache, to_bmp_bytes
from eink_dashboard.render.layout import HEIGHT, WIDTH, render
from eink_dashboard.render.viewmodel import (
    AlertRow,
    BikeRow,
    DashboardView,
    DepartureRow,
    WeatherRow,
)

VIEW = DashboardView(
    as_of="08:00",
    departures=(
        DepartureRow("T2", "St-Priest", "2 min", ("9 min", "15 min", "21 min")),
        DepartureRow("T2", "Perrache", "4 min", ("12 min",)),
    ),
    bikes=(BikeRow("Blandan", 0, False), BikeRow("Berthelot", 4, False)),
    alerts=(),
    weather=WeatherRow("12°C", "Pluie vers 15h"),
    traffic_note="",
)

EMPTY = DashboardView(
    as_of="08:00", departures=(), bikes=(), alerts=(), weather=None, traffic_note=""
)


def test_render_produces_a_one_bit_image_of_the_right_size() -> None:
    image = render(VIEW)

    assert image.size == (WIDTH, HEIGHT)
    assert image.mode == "1"


def test_render_handles_an_empty_view() -> None:
    assert render(EMPTY).size == (WIDTH, HEIGHT)


def test_render_is_deterministic() -> None:
    assert to_bmp_bytes(render(VIEW)) == to_bmp_bytes(render(VIEW))


def test_different_content_produces_different_bytes() -> None:
    other = DashboardView(
        as_of="08:00",
        departures=VIEW.departures,
        bikes=(BikeRow("Blandan", 3, False), BikeRow("Berthelot", 4, False)),
        alerts=VIEW.alerts,
        weather=VIEW.weather,
        traffic_note="",
    )

    assert to_bmp_bytes(render(VIEW)) != to_bmp_bytes(render(other))


def test_bmp_output_is_one_bit_per_pixel() -> None:
    payload = to_bmp_bytes(render(VIEW))

    assert payload[:2] == b"BM"
    assert int.from_bytes(payload[28:30], "little") == 1


def test_render_survives_very_long_labels_and_two_alerts() -> None:
    long_view = DashboardView(
        as_of="08:00",
        departures=(DepartureRow("T2", "Une destination vraiment tres longue" * 3, "2 min", ()),),
        bikes=(BikeRow("Un nom de station particulierement long", 0, True),),
        alerts=(
            AlertRow("T2", "Trafic perturbé " * 20),
            AlertRow("D", "Station non desservie " * 10),
        ),
        weather=WeatherRow("", "Météo indisponible"),
        traffic_note="",
    )

    assert render(long_view).size == (WIDTH, HEIGHT)


def test_image_cache_evicts_the_oldest_entry() -> None:
    cache = ImageCache(max_entries=2)
    cache.put("a", b"1")
    cache.put("b", b"2")
    cache.put("c", b"3")

    assert cache.get("a") is None
    assert cache.get("c") == b"3"
