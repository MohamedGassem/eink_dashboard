from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx

from eink_dashboard.core.config import WeatherConfig
from eink_dashboard.providers.weather.client import FORECAST_URL, WeatherClient

FIXTURES = Path(__file__).parent.parent / "fixtures"
PARIS = ZoneInfo("Europe/Paris")
BODY = (FIXTURES / "open_meteo_forecast.json").read_text(encoding="utf-8")
CONFIG = WeatherConfig(latitude=45.75, longitude=4.85)


def _client(http: httpx.AsyncClient) -> WeatherClient:
    return WeatherClient(http, CONFIG, tz=PARIS)


@respx.mock
async def test_fetch_returns_snapshot() -> None:
    respx.get(FORECAST_URL).mock(return_value=httpx.Response(200, text=BODY))

    async with httpx.AsyncClient() as http:
        snapshot = await _client(http).fetch()

    assert snapshot.data.temperature_c == 18.3
    assert snapshot.source_updated_at == snapshot.data.reported_at


@respx.mock
async def test_fetch_requests_paris_timezone_and_minimal_fields() -> None:
    route = respx.get(FORECAST_URL).mock(return_value=httpx.Response(200, text=BODY))

    async with httpx.AsyncClient() as http:
        await _client(http).fetch()

    url = route.calls[0].request.url
    assert url.params["timezone"] == "Europe/Paris"
    assert url.params["current"] == "temperature_2m"
    assert url.params["hourly"] == "precipitation_probability,precipitation"


@respx.mock
async def test_http_error_propagates() -> None:
    respx.get(FORECAST_URL).mock(return_value=httpx.Response(500))

    async with httpx.AsyncClient() as http:
        with pytest.raises(httpx.HTTPStatusError):
            await _client(http).fetch()
