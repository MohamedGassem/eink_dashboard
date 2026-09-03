from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from eink_dashboard.core.config import WeatherConfig
from eink_dashboard.providers.weather.client import WeatherClient

PARIS = ZoneInfo("Europe/Paris")


@pytest.mark.network
async def test_live_open_meteo_returns_snapshot() -> None:
    config = WeatherConfig(latitude=45.749, longitude=4.855)

    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as http:
        snapshot = await WeatherClient(http, config, tz=PARIS).fetch()

    assert -40.0 < snapshot.data.temperature_c < 55.0
    assert snapshot.data.reported_at.tzinfo is not None
    if snapshot.data.rain_at is not None:
        assert snapshot.data.rain_at >= datetime.now(PARIS).replace(
            minute=0, second=0, microsecond=0
        )
