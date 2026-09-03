from datetime import datetime
from io import BytesIO
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from eink_dashboard.api.routes import device, display
from eink_dashboard.core.config import DashboardConfig, Settings
from eink_dashboard.domain.bikes import BikeStation
from eink_dashboard.services.dashboard import NIGHT_MAX_SLEEP
from eink_dashboard.state import Store

MAC = "AA:BB:CC:DD:EE:FF"
KEY = "cle-de-test"
# Horloge figée en pleine pointe du matin : hors fenêtre « coarse » (09:00-21:00)
# et hors fenêtre nuit (21:00-07:30), le hash réagit à chaque valeur affichée.
# Sans ça les tests d'ETag dépendraient de l'heure réelle d'exécution.
NOW = datetime(2026, 9, 2, 8, 0, tzinfo=ZoneInfo("Europe/Paris"))


class _FixedClock(datetime):
    @classmethod
    def now(cls, tz: object = None) -> datetime:  # type: ignore[override]
        return NOW.astimezone(tz) if tz is not None else NOW.replace(tzinfo=None)


@pytest.fixture(autouse=True)
def _freeze_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(display, "datetime", _FixedClock)
    monkeypatch.setattr(device, "datetime", _FixedClock)


def build_client(store: Store | None = None, config: DashboardConfig | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(display.router)
    app.include_router(device.router)
    app.state.store = store or Store()
    app.state.config = config or DashboardConfig()
    app.state.images = display.ImageCache()
    app.state.tz = ZoneInfo("Europe/Paris")
    app.state.settings = Settings(
        _env_file=None,
        device_mac=MAC,
        device_api_key=KEY,
        public_base_url="http://server:8000",
    )
    return TestClient(app)


def _bikes(count: int, docks: int) -> tuple[BikeStation, ...]:
    return (BikeStation("7052", "Blandan", count, count, 0, docks, 20, True, NOW),)


def _store_with_bikes(count: int, docks: int) -> Store:
    store = Store()
    store.record_success("velov", _bikes(count, docks), NOW)
    return store


# --- /api/v1/display/meta ---------------------------------------------------


def test_meta_returns_exactly_hash_and_refresh_seconds() -> None:
    body = build_client().get("/api/v1/display/meta").json()

    assert set(body) == {"content_hash", "refresh_seconds"}


def test_meta_content_hash_is_16_hex_chars() -> None:
    content_hash = build_client().get("/api/v1/display/meta").json()["content_hash"]

    assert len(content_hash) == 16
    assert all(c in "0123456789abcdef" for c in content_hash)


def test_meta_refresh_seconds_matches_the_schedule() -> None:
    refresh_seconds = build_client().get("/api/v1/display/meta").json()["refresh_seconds"]

    assert 0 < refresh_seconds <= NIGHT_MAX_SLEEP


def test_meta_responds_when_the_backend_has_no_data() -> None:
    response = build_client().get("/api/v1/display/meta")

    assert response.status_code == 200
    assert response.json()["content_hash"]


# --- /image/dashboard.bmp --------------------------------------------------


def test_bmp_is_served_as_a_1bit_800x480_bitmap() -> None:
    response = build_client().get("/image/dashboard.bmp")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/bmp"
    assert response.content[:2] == b"BM"

    image = Image.open(BytesIO(response.content))
    assert image.mode == "1"
    assert image.size == (800, 480)


def test_bmp_carries_a_no_cache_etag() -> None:
    response = build_client().get("/image/dashboard.bmp")

    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["etag"].strip('"')


def test_bmp_etag_equals_meta_content_hash() -> None:
    client = build_client()
    etag = client.get("/image/dashboard.bmp").headers["etag"].strip('"')
    content_hash = client.get("/api/v1/display/meta").json()["content_hash"]

    assert etag == content_hash


def test_bmp_etag_is_stable_when_nothing_changes() -> None:
    client = build_client()
    first = client.get("/image/dashboard.bmp").headers["etag"]
    second = client.get("/image/dashboard.bmp").headers["etag"]

    assert first == second


def test_bmp_etag_ignores_a_change_that_is_not_displayed() -> None:
    store = _store_with_bikes(5, 10)
    client = build_client(store)
    first = client.get("/image/dashboard.bmp").headers["etag"]

    store.record_success("velov", _bikes(5, 3), NOW)  # bornes libres : non affiché
    assert client.get("/image/dashboard.bmp").headers["etag"] == first


def test_bmp_etag_changes_when_a_visible_value_changes() -> None:
    store = _store_with_bikes(5, 10)
    client = build_client(store)
    first = client.get("/image/dashboard.bmp").headers["etag"]

    store.record_success("velov", _bikes(2, 13), NOW)  # vélos dispo : affiché
    assert client.get("/image/dashboard.bmp").headers["etag"] != first


def test_bmp_returns_304_when_if_none_match_is_current() -> None:
    client = build_client()
    etag = client.get("/image/dashboard.bmp").headers["etag"]

    response = client.get("/image/dashboard.bmp", headers={"If-None-Match": etag})

    assert response.status_code == 304
    assert response.content == b""
    assert response.headers["etag"] == etag


def test_bmp_returns_200_when_if_none_match_is_stale() -> None:
    response = build_client().get(
        "/image/dashboard.bmp", headers={"If-None-Match": '"0000000000000000"'}
    )

    assert response.status_code == 200
    assert response.content[:2] == b"BM"


def test_bmp_route_wins_over_the_trmnl_image_route() -> None:
    # device.router expose /image/{name} ; la route littérale doit primer.
    response = build_client().get("/image/dashboard.bmp")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/bmp"


# --- /image/dashboard.png (fallback online_image) -------------------------


def test_png_is_served_as_a_1bit_800x480_bitmap_with_the_same_etag() -> None:
    client = build_client()
    response = client.get("/image/dashboard.png")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"

    image = Image.open(BytesIO(response.content))
    assert image.mode == "1"
    assert image.size == (800, 480)

    bmp_etag = client.get("/image/dashboard.bmp").headers["etag"]
    assert response.headers["etag"] == bmp_etag


def test_png_supports_conditional_requests() -> None:
    client = build_client()
    etag = client.get("/image/dashboard.png").headers["etag"]

    assert client.get("/image/dashboard.png", headers={"If-None-Match": etag}).status_code == 304
