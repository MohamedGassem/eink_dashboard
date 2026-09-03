"""Bout-en-bout V2 : les 4 providers câblés, endpoints et états dégradés.

Complète les tests unitaires par une vérification à travers toute la pile
FastAPI + scheduler + rendu.
"""

import json
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from eink_dashboard.core.config import get_settings
from eink_dashboard.main import app, lifespan
from eink_dashboard.providers.tcl.client import PASSAGES_URL
from eink_dashboard.providers.tcl_sx.client import SITUATION_EXCHANGE_URL
from eink_dashboard.providers.velov.client import INFORMATION_URL, STATUS_URL
from eink_dashboard.providers.weather.client import FORECAST_URL
from eink_dashboard.state import Store

FIXTURES = Path(__file__).parent.parent / "fixtures"
VELOV_STATUS = json.loads((FIXTURES / "velov_station_status.json").read_text(encoding="utf-8"))
VELOV_INFO = json.loads((FIXTURES / "velov_station_information.json").read_text(encoding="utf-8"))
WEATHER = json.loads((FIXTURES / "open_meteo_forecast.json").read_text(encoding="utf-8"))
SX_T2_D = json.loads((FIXTURES / "tcl_situation_exchange_t2_d.json").read_text(encoding="utf-8"))

TCL_PASSAGES = {
    "nb_results": 1,
    "values": [
        {
            "id": 32146,
            "ligne": "T2",
            "direction": "Saint-Priest Bel Air",
            "heurepassage": "2100-01-01 08:05:00",
            "type": "E",
        }
    ],
}


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    config = tmp_path / "dashboard.toml"
    config.write_text(
        '[[tcl.stops]]\nname = "Route de Vienne"\nstop_id = "32146"\nlines = ["T2"]\n'
        '[[tcl.direction_aliases]]\nmatch = "Saint-Priest"\nlabel = "St-Priest"\n'
        '[tcl.disruptions]\nlines = ["T2", "D"]\n'
        '[[tcl.disruptions.line_refs]]\nlabel = "T2"\nrefs = ["ActIV:Line::T2:SYTRAL"]\n'
        '[[tcl.disruptions.line_refs]]\nlabel = "D"\nrefs = ["ActIV:Line::D:SYTRAL"]\n'
        '[[velov.stations]]\nstation_id = "1032"\nlabel = "Blandan"\n'
        "[weather]\nlatitude = 45.75\nlongitude = 4.85\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CONFIG_PATH", str(config))
    monkeypatch.setenv("GRANDLYON_USERNAME", "u")
    monkeypatch.setenv("GRANDLYON_PASSWORD", "p")
    monkeypatch.setenv("DEVICE_MAC", "AA:BB:CC:DD:EE:FF")
    monkeypatch.setenv("DEVICE_API_KEY", "k")
    monkeypatch.setenv("TCL_DISRUPTIONS_REFRESH_SECONDS", "1")
    monkeypatch.setenv("WEATHER_REFRESH_SECONDS", "1")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def _wait(store: Store, predicate: object) -> None:
    import asyncio

    for _ in range(400):
        if predicate():  # type: ignore[operator]
            return
        await asyncio.sleep(0)
    raise AssertionError("providers non peuplés à temps")


@respx.mock
async def test_full_stack_serves_every_v2_signal(configured: None) -> None:
    respx.get(STATUS_URL).mock(return_value=httpx.Response(200, json=VELOV_STATUS))
    respx.get(INFORMATION_URL).mock(return_value=httpx.Response(200, json=VELOV_INFO))
    respx.get(PASSAGES_URL).mock(return_value=httpx.Response(200, json=TCL_PASSAGES))
    respx.get(SITUATION_EXCHANGE_URL).mock(return_value=httpx.Response(200, json=SX_T2_D))
    respx.get(FORECAST_URL).mock(return_value=httpx.Response(200, json=WEATHER))

    async with lifespan(app):
        store: Store = app.state.store
        await _wait(
            store,
            lambda: (
                store.state.weather.data is not None
                and store.state.tcl_disruptions.data is not None
                and store.state.velov.data is not None
            ),
        )
        client = TestClient(app)

        health = client.get("/health").json()["providers"]
        assert set(health) == {"tcl", "velov", "tcl_disruptions", "weather"}

        payload = client.get("/api/v1/dashboard").json()
        assert payload["tcl_disruptions"]["status"] == "ok"
        lines = {tuple(d["lines"]) for d in payload["tcl_disruptions"]["disruptions"]}
        assert ("T2",) in lines
        assert ("D",) in lines
        assert payload["weather"]["snapshot"]["temperature_c"] == 18.3

        assert client.get("/preview.png").content[:8] == b"\x89PNG\r\n\x1a\n"
        display = client.get(
            "/api/display", headers={"ID": "AA:BB:CC:DD:EE:FF", "Access-Token": "k"}
        ).json()
        assert display["filename"].endswith(".bmp")
        image = client.get(f"/image/{display['filename']}")
        assert image.content[:2] == b"BM"


@respx.mock
async def test_siri_timeout_is_never_read_as_normal_traffic(configured: None) -> None:
    respx.get(STATUS_URL).mock(return_value=httpx.Response(200, json=VELOV_STATUS))
    respx.get(INFORMATION_URL).mock(return_value=httpx.Response(200, json=VELOV_INFO))
    respx.get(PASSAGES_URL).mock(return_value=httpx.Response(200, json=TCL_PASSAGES))
    respx.get(SITUATION_EXCHANGE_URL).mock(side_effect=httpx.ReadTimeout("trop lent"))
    respx.get(FORECAST_URL).mock(return_value=httpx.Response(200, json=WEATHER))

    async with lifespan(app):
        store: Store = app.state.store
        await _wait(store, lambda: store.state.tcl_disruptions.last_error is not None)

        payload = TestClient(app).get("/api/v1/dashboard").json()
        assert payload["tcl_disruptions"]["status"] in {"unavailable", "degraded", "stale"}
        assert payload["tcl_disruptions"]["last_error"] is not None
