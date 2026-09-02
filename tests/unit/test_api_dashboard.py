from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient

from eink_dashboard.api.routes import dashboard, health
from eink_dashboard.core.config import Settings
from eink_dashboard.domain.bikes import BikeStation
from eink_dashboard.domain.transit import Departure, StopBoard
from eink_dashboard.state import Store

T0 = datetime(2026, 9, 2, 8, 0, tzinfo=UTC)


def build_client(store: Store) -> TestClient:
    app = FastAPI()
    app.include_router(health.router)
    app.include_router(dashboard.router)
    app.state.store = store
    app.state.settings = Settings(_env_file=None)
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
