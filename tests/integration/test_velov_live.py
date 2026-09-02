import httpx
import pytest

from eink_dashboard.core.config import VelovStation
from eink_dashboard.providers.velov.client import VelovClient


@pytest.mark.network
async def test_live_velov_returns_configured_station() -> None:
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as http:
        client = VelovClient(http, [VelovStation(station_id="1024", label="Rouville")])
        stations = await client.fetch()

    assert len(stations) == 1
    assert stations[0].capacity > 0
