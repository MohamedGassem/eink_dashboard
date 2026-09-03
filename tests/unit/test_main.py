import json
from collections.abc import Iterator
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx

from eink_dashboard.core.config import get_settings
from eink_dashboard.main import app, lifespan
from eink_dashboard.providers.tcl.client import PASSAGES_URL
from eink_dashboard.providers.velov.client import INFORMATION_URL, STATUS_URL
from eink_dashboard.state import Store

FIXTURES = Path(__file__).parent.parent / "fixtures"
STATUS = json.loads((FIXTURES / "velov_station_status.json").read_text(encoding="utf-8"))
INFORMATION = json.loads((FIXTURES / "velov_station_information.json").read_text(encoding="utf-8"))


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    config = tmp_path / "dashboard.toml"
    config.write_text(
        '[[velov.stations]]\nstation_id = "1032"\nlabel = "Pizay"\n', encoding="utf-8"
    )
    monkeypatch.setenv("CONFIG_PATH", str(config))
    monkeypatch.setenv("GRANDLYON_USERNAME", "")
    monkeypatch.setenv("GRANDLYON_PASSWORD", "")
    monkeypatch.setenv("TZ", "Europe/Paris")
    monkeypatch.setenv("DEVICE_MAC", "AA:BB:CC:DD:EE:FF")
    monkeypatch.setenv("DEVICE_API_KEY", "cle-de-test")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@respx.mock
async def test_lifespan_wires_state_onto_the_app(env: None) -> None:
    respx.get(STATUS_URL).mock(return_value=httpx.Response(200, json=STATUS))
    respx.get(INFORMATION_URL).mock(return_value=httpx.Response(200, json=INFORMATION))

    async with lifespan(app):
        assert isinstance(app.state.store, Store)
        assert app.state.settings.tz == "Europe/Paris"
        assert app.state.tz == ZoneInfo("Europe/Paris")


async def test_lifespan_fails_fast_when_tcl_configured_without_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = tmp_path / "dashboard.toml"
    config.write_text(
        '[[tcl.stops]]\nname = "Bellecour"\nstop_id = "1234"\nlines = ["A"]\n', encoding="utf-8"
    )
    monkeypatch.setenv("CONFIG_PATH", str(config))
    monkeypatch.setenv("GRANDLYON_USERNAME", "")
    monkeypatch.setenv("GRANDLYON_PASSWORD", "")
    get_settings.cache_clear()

    with pytest.raises(ValueError, match="GRANDLYON_USERNAME"):
        async with lifespan(app):
            pass

    get_settings.cache_clear()


async def test_lifespan_fails_fast_when_device_api_key_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = tmp_path / "dashboard.toml"
    config.write_text(
        '[[velov.stations]]\nstation_id = "1032"\nlabel = "Pizay"\n', encoding="utf-8"
    )
    monkeypatch.setenv("CONFIG_PATH", str(config))
    monkeypatch.setenv("GRANDLYON_USERNAME", "")
    monkeypatch.setenv("GRANDLYON_PASSWORD", "")
    monkeypatch.setenv("DEVICE_MAC", "AA:BB:CC:DD:EE:FF")
    monkeypatch.setenv("DEVICE_API_KEY", "")
    get_settings.cache_clear()

    with pytest.raises(ValueError, match="DEVICE_API_KEY"):
        async with lifespan(app):
            pass

    get_settings.cache_clear()


@respx.mock
async def test_provider_loops_populate_the_store(env: None) -> None:
    respx.get(STATUS_URL).mock(return_value=httpx.Response(200, json=STATUS))
    respx.get(INFORMATION_URL).mock(return_value=httpx.Response(200, json=INFORMATION))
    respx.get(PASSAGES_URL).mock(
        return_value=httpx.Response(200, json={"nb_results": 0, "values": []})
    )

    async with lifespan(app):
        store: Store = app.state.store
        for _ in range(50):
            if store.state.velov.data is not None:
                break
            await _tick()

    assert store.state.velov.data is not None
    assert store.state.velov.data[0].label == "Pizay"


async def _tick() -> None:
    import asyncio

    await asyncio.sleep(0)
