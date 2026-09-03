from eink_dashboard.render.images import ImageCache, to_bmp_bytes
from eink_dashboard.render.layout import HEIGHT, WIDTH, render
from eink_dashboard.render.viewmodel import BikeBlock, DashboardView, DepartureLine, StopBlock

VIEW = DashboardView(
    as_of="08:00",
    stops=(
        StopBlock(
            title="Bellecour",
            lines=(
                DepartureLine("A", "Vaulx-en-Velin La Soie", ("2 min", "9 min")),
                DepartureLine("D", "Gare de Venissieux", ("4 min",)),
            ),
            stale=False,
            note="",
        ),
    ),
    bikes=(BikeBlock("Pizay", 12, 7, 20, False, ""),),
)

EMPTY = DashboardView(as_of="08:00", stops=(), bikes=())


def test_render_produces_a_one_bit_image_of_the_right_size() -> None:
    image = render(VIEW)

    assert image.size == (WIDTH, HEIGHT)
    assert image.mode == "1"


def test_render_handles_an_empty_view() -> None:
    image = render(EMPTY)

    assert image.size == (WIDTH, HEIGHT)


def test_render_is_deterministic() -> None:
    assert to_bmp_bytes(render(VIEW)) == to_bmp_bytes(render(VIEW))


def test_different_content_produces_different_bytes() -> None:
    other = DashboardView(
        as_of="08:00", stops=VIEW.stops, bikes=(BikeBlock("Pizay", 3, 16, 20, False, ""),)
    )

    assert to_bmp_bytes(render(VIEW)) != to_bmp_bytes(render(other))


def test_bmp_output_is_one_bit_per_pixel() -> None:
    payload = to_bmp_bytes(render(VIEW))

    assert payload[:2] == b"BM"
    assert int.from_bytes(payload[28:30], "little") == 1


def test_render_survives_a_very_long_direction_label() -> None:
    long_view = DashboardView(
        as_of="08:00",
        stops=(
            StopBlock(
                title="Un nom d arret particulierement long",
                lines=(DepartureLine("A", "Une destination vraiment tres longue" * 3, ("2 min",)),),
                stale=True,
                note="maj 07:12",
            ),
        ),
        bikes=(),
    )

    assert render(long_view).size == (WIDTH, HEIGHT)


def test_image_cache_evicts_the_oldest_entry() -> None:
    cache = ImageCache(max_entries=2)
    cache.put("a", b"1")
    cache.put("b", b"2")
    cache.put("c", b"3")

    assert cache.get("a") is None
    assert cache.get("c") == b"3"
