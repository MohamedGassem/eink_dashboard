from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient

from eink_dashboard.api.routes import device
from eink_dashboard.core.config import (
    DashboardConfig,
    DisruptionLine,
    DisruptionsConfig,
    Settings,
)
from eink_dashboard.domain.bikes import BikeStation
from eink_dashboard.domain.disruptions import TransitDisruption
from eink_dashboard.domain.transit import Departure, StopBoard
from eink_dashboard.render.images import ImageCache
from eink_dashboard.state import Store

MAC = "AA:BB:CC:DD:EE:FF"
KEY = "cle-de-test"

DISRUPTIONS_CONFIG = DashboardConfig(
    disruptions=DisruptionsConfig(
        lines=["T2"], line_refs=[DisruptionLine(label="T2", refs=["ActIV:Line::T2:SYTRAL"])]
    )
)


def build_client(store: Store | None = None, config: DashboardConfig | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(device.router)
    app.state.store = store or Store()
    app.state.config = config or DashboardConfig()
    app.state.images = ImageCache()
    app.state.tz = ZoneInfo("Europe/Paris")
    app.state.settings = Settings(
        _env_file=None,
        device_mac=MAC,
        device_api_key=KEY,
        public_base_url="http://server:8000",
    )
    return TestClient(app)


def _filename(client: TestClient) -> str:
    body = client.get("/api/display", headers={"ID": MAC, "Access-Token": KEY}).json()
    return str(body["filename"])


def test_setup_returns_the_api_key_for_the_known_mac() -> None:
    response = build_client().get("/api/setup", headers={"ID": MAC})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == 200
    assert body["api_key"] == KEY
    assert body["image_url"].startswith("http://server:8000/image/")


def test_setup_is_case_insensitive_on_the_mac() -> None:
    response = build_client().get("/api/setup", headers={"ID": MAC.lower()})

    assert response.json()["api_key"] == KEY


def test_setup_rejects_an_unknown_mac() -> None:
    response = build_client().get("/api/setup", headers={"ID": "11:22:33:44:55:66"})

    assert response.status_code == 404


def test_display_returns_an_image_url_and_a_refresh_rate() -> None:
    response = build_client().get(
        "/api/display",
        headers={"ID": MAC, "Access-Token": KEY, "Battery-Voltage": "4.05", "RSSI": "-62"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["filename"].endswith(".bmp")
    assert body["image_url"].endswith(body["filename"])
    assert body["refresh_rate"] > 0
    assert body["update_firmware"] is False


def test_display_refresh_rate_matches_the_schedule() -> None:
    from eink_dashboard.services.dashboard import NIGHT_MAX_SLEEP

    body = build_client().get("/api/display", headers={"ID": MAC, "Access-Token": KEY}).json()

    assert 0 < body["refresh_rate"] <= NIGHT_MAX_SLEEP


def test_display_rejects_a_bad_token() -> None:
    response = build_client().get(
        "/api/display", headers={"ID": MAC, "Access-Token": "mauvaise-cle"}
    )

    assert response.status_code == 401


def test_display_is_stable_when_the_state_does_not_change() -> None:
    client = build_client()
    first = client.get("/api/display", headers={"ID": MAC, "Access-Token": KEY}).json()
    second = client.get("/api/display", headers={"ID": MAC, "Access-Token": KEY}).json()

    assert first["filename"] == second["filename"]


def test_image_is_served_as_bmp() -> None:
    client = build_client()
    body = client.get("/api/display", headers={"ID": MAC, "Access-Token": KEY}).json()
    filename = body["filename"]

    response = client.get(f"/image/{filename}")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/bmp"
    assert response.content[:2] == b"BM"


def test_unknown_image_returns_404() -> None:
    response = build_client().get("/image/inconnue.bmp")

    assert response.status_code == 404


NOW = datetime.now(ZoneInfo("Europe/Paris"))


def _bikes(count: int, docks: int) -> tuple[BikeStation, ...]:
    return (BikeStation("7052", "Blandan", count, count, 0, docks, 20, True, NOW),)


def test_velov_docks_change_alone_keeps_the_same_image() -> None:
    store = Store()
    store.record_success("velov", _bikes(5, 10), NOW)
    client = build_client(store)
    first = _filename(client)

    store.record_success("velov", _bikes(5, 3), NOW)
    assert _filename(client) == first


def test_velov_bike_count_change_produces_a_new_image() -> None:
    store = Store()
    store.record_success("velov", _bikes(5, 10), NOW)
    client = build_client(store)
    first = _filename(client)

    store.record_success("velov", _bikes(2, 13), NOW)
    assert _filename(client) != first


def test_adding_and_removing_a_disruption_changes_the_image() -> None:
    store = Store()
    store.record_success("tcl_disruptions", (), NOW)
    client = build_client(store, DISRUPTIONS_CONFIG)
    clear = _filename(client)

    disruption = TransitDisruption(
        source_id="S1",
        lines=("T2",),
        summary="Trafic perturbé",
        description="Trafic perturbé",
        valid_from=NOW - timedelta(hours=1),
        valid_until=NOW + timedelta(hours=2),
        severity=None,
        planned=None,
    )
    store.record_success("tcl_disruptions", (disruption,), NOW)
    disturbed = _filename(client)
    assert disturbed != clear

    store.record_success("tcl_disruptions", (), NOW)
    assert _filename(client) == clear


def test_a_departure_crossing_a_minute_boundary_changes_the_image() -> None:
    store = Store()
    board = StopBoard(
        stop_name="Route de Vienne",
        departures=(Departure("T2", "St-Priest", NOW + timedelta(seconds=125), True),),
    )
    store.record_success("tcl", (board,), NOW)
    client = build_client(store)
    first = _filename(client)

    later = StopBoard(
        stop_name="Route de Vienne",
        departures=(Departure("T2", "St-Priest", NOW + timedelta(seconds=55), True),),
    )
    store.record_success("tcl", (later,), NOW)
    assert _filename(client) != first


def test_polling_without_state_change_serves_one_cached_image() -> None:
    store = Store()
    store.record_success("velov", _bikes(5, 10), NOW)
    client = build_client(store)

    names = {_filename(client) for _ in range(5)}
    assert len(names) == 1


def test_log_endpoint_accepts_any_payload() -> None:
    response = build_client().post(
        "/api/log", headers={"ID": MAC, "Access-Token": KEY}, json={"log": {"message": "boum"}}
    )

    assert response.status_code == 204
