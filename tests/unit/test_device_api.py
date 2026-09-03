from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient

from eink_dashboard.api.routes import device
from eink_dashboard.core.config import DashboardConfig, Settings
from eink_dashboard.render.images import ImageCache
from eink_dashboard.state import Store

MAC = "AA:BB:CC:DD:EE:FF"
KEY = "cle-de-test"


def build_client() -> TestClient:
    app = FastAPI()
    app.include_router(device.router)
    app.state.store = Store()
    app.state.config = DashboardConfig()
    app.state.images = ImageCache()
    app.state.tz = ZoneInfo("Europe/Paris")
    app.state.settings = Settings(
        _env_file=None,
        device_mac=MAC,
        device_api_key=KEY,
        public_base_url="http://server:8000",
    )
    return TestClient(app)


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
    from eink_dashboard.services.dashboard import DAY_REFRESH, NIGHT_REFRESH, PEAK_REFRESH

    body = build_client().get("/api/display", headers={"ID": MAC, "Access-Token": KEY}).json()

    assert body["refresh_rate"] in {PEAK_REFRESH, DAY_REFRESH, NIGHT_REFRESH}


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


def test_log_endpoint_accepts_any_payload() -> None:
    response = build_client().post(
        "/api/log", headers={"ID": MAC, "Access-Token": KEY}, json={"log": {"message": "boum"}}
    )

    assert response.status_code == 204
