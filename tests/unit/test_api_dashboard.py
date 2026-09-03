from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient

from eink_dashboard.api.routes import dashboard, health
from eink_dashboard.core.config import DashboardConfig, Settings
from eink_dashboard.domain.bikes import BikeStation
from eink_dashboard.domain.disruptions import TransitDisruption
from eink_dashboard.domain.transit import Departure, StopBoard
from eink_dashboard.domain.weather import WeatherSnapshot
from eink_dashboard.state import Store

T0 = datetime(2026, 9, 2, 8, 0, tzinfo=UTC)


def build_client(store: Store) -> TestClient:
    app = FastAPI()
    app.include_router(health.router)
    app.include_router(dashboard.router)
    app.state.store = store
    app.state.settings = Settings(_env_file=None)
    app.state.config = DashboardConfig()
    app.state.tz = ZoneInfo("Europe/Paris")
    return TestClient(app)


def filled_store(now: datetime = T0) -> Store:
    store = Store()
    store.record_success(
        "tcl",
        (
            StopBoard(
                stop_name="Bellecour",
                departures=(Departure("A", "Vaulx", now + timedelta(minutes=3, seconds=30), True),),
            ),
        ),
        now,
    )
    store.record_success("velov", (BikeStation("1032", "Pizay", 12, 8, 4, 7, 20, True, now),), now)
    store.record_success(
        "tcl_disruptions",
        (
            TransitDisruption(
                source_id="S1",
                lines=("T2",),
                summary="Trafic perturbé",
                description="Trafic perturbé entre Jean Macé et Perrache.",
                valid_from=now - timedelta(hours=1),
                valid_until=now + timedelta(hours=2),
                severity=None,
                planned=None,
            ),
        ),
        now,
    )
    store.record_success(
        "weather",
        WeatherSnapshot(temperature_c=18.3, rain_at=now + timedelta(hours=2), reported_at=now),
        now,
    )
    return store


def test_health_reports_each_provider() -> None:
    now = datetime.now(ZoneInfo("Europe/Paris"))
    response = build_client(filled_store(now)).get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["providers"]["tcl"]["status"] == "ok"
    assert body["providers"]["velov"]["status"] == "ok"
    assert body["providers"]["tcl"]["age_seconds"] is not None
    assert body["providers"]["tcl"]["last_success_at"] is not None


def test_health_still_returns_200_when_a_provider_is_degraded() -> None:
    now = datetime.now(ZoneInfo("Europe/Paris"))
    store = filled_store(now)
    store.record_failure("tcl", "timeout", now + timedelta(seconds=60))

    response = build_client(store).get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["providers"]["tcl"]["status"] == "degraded"
    assert body["providers"]["tcl"]["last_error"] == "timeout"


def test_health_reports_unavailable_on_a_fresh_store() -> None:
    body = build_client(Store()).get("/health").json()

    assert body["providers"]["tcl"]["status"] == "unavailable"
    assert body["providers"]["tcl"]["age_seconds"] is None
    assert body["providers"]["tcl"]["last_success_at"] is None


def test_health_reports_stale_when_data_is_older_than_three_intervals() -> None:
    old = datetime.now(ZoneInfo("Europe/Paris")) - timedelta(seconds=60 * 3 + 10)
    store = Store()
    store.record_success("velov", (BikeStation("1032", "Pizay", 1, 1, 0, 1, 20, True, old),), old)

    body = build_client(store).get("/health").json()

    assert body["providers"]["velov"]["status"] == "stale"


def test_dashboard_returns_both_sources() -> None:
    now = datetime.now(ZoneInfo("Europe/Paris"))
    body = build_client(filled_store(now)).get("/api/v1/dashboard").json()

    assert body["tcl"]["status"] == "ok"
    assert body["tcl"]["stops"][0]["stop_name"] == "Bellecour"
    assert body["tcl"]["stops"][0]["available"] is True
    assert body["tcl"]["stops"][0]["departures"][0]["line"] == "A"
    assert body["tcl"]["stops"][0]["departures"][0]["minutes"] == 3
    assert body["velov"]["stations"][0]["label"] == "Pizay"
    assert body["velov"]["stations"][0]["capacity"] == 20


def test_dashboard_returns_empty_lists_without_data() -> None:
    body = build_client(Store()).get("/api/v1/dashboard").json()

    assert body["tcl"]["status"] == "unavailable"
    assert body["tcl"]["stops"] == []
    assert body["velov"]["stations"] == []
    assert body["tcl_disruptions"]["status"] == "unavailable"
    assert body["tcl_disruptions"]["disruptions"] == []
    assert body["weather"]["status"] == "unavailable"
    assert body["weather"]["snapshot"] is None


def test_dashboard_exposes_disruptions_and_weather() -> None:
    now = datetime.now(ZoneInfo("Europe/Paris"))
    body = build_client(filled_store(now)).get("/api/v1/dashboard").json()

    assert body["tcl_disruptions"]["status"] == "ok"
    assert body["tcl_disruptions"]["disruptions"][0]["lines"] == ["T2"]
    assert body["weather"]["status"] == "ok"
    assert body["weather"]["snapshot"]["temperature_c"] == 18.3


def test_health_reports_v2_providers() -> None:
    now = datetime.now(ZoneInfo("Europe/Paris"))
    body = build_client(filled_store(now)).get("/health").json()

    assert body["providers"]["tcl_disruptions"]["status"] == "ok"
    assert body["providers"]["weather"]["status"] == "ok"


def test_preview_png_renders_an_image() -> None:
    now = datetime.now(ZoneInfo("Europe/Paris"))
    response = build_client(filled_store(now)).get("/preview.png")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_preview_png_works_on_an_empty_store() -> None:
    response = build_client(Store()).get("/preview.png")

    assert response.status_code == 200
    assert response.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_dashboard_marks_a_failed_stop_as_unavailable() -> None:
    now = datetime.now(ZoneInfo("Europe/Paris"))
    store = Store()
    store.record_success(
        "tcl",
        (StopBoard(stop_name="Part-Dieu", departures=(), available=False),),
        now,
    )
    body = build_client(store).get("/api/v1/dashboard").json()

    assert body["tcl"]["stops"][0]["available"] is False
    assert body["tcl"]["stops"][0]["departures"] == []
