import json
from pathlib import Path

import httpx
import pytest
import respx

from eink_dashboard.core.config import VelovStation
from eink_dashboard.providers.velov.client import INFORMATION_URL, STATUS_URL, VelovClient

FIXTURES = Path(__file__).parent.parent / "fixtures"
STATUS = json.loads((FIXTURES / "velov_station_status.json").read_text(encoding="utf-8"))
INFORMATION = json.loads((FIXTURES / "velov_station_information.json").read_text(encoding="utf-8"))
CONFIGURED = [VelovStation(station_id="1032", label="Pizay")]


@respx.mock
async def test_fetch_returns_domain_objects() -> None:
    respx.get(STATUS_URL).mock(return_value=httpx.Response(200, json=STATUS))
    respx.get(INFORMATION_URL).mock(return_value=httpx.Response(200, json=INFORMATION))

    async with httpx.AsyncClient() as http:
        stations = await VelovClient(http, CONFIGURED).fetch()

    assert len(stations) == 1
    assert stations[0].label == "Pizay"
    assert stations[0].bikes_available == 12


@respx.mock
async def test_information_feed_is_cached_between_calls() -> None:
    respx.get(STATUS_URL).mock(return_value=httpx.Response(200, json=STATUS))
    information_route = respx.get(INFORMATION_URL).mock(
        return_value=httpx.Response(200, json=INFORMATION)
    )

    async with httpx.AsyncClient() as http:
        client = VelovClient(http, CONFIGURED)
        await client.fetch()
        await client.fetch()

    assert information_route.call_count == 1


@respx.mock
async def test_server_error_raises() -> None:
    respx.get(STATUS_URL).mock(return_value=httpx.Response(500))
    respx.get(INFORMATION_URL).mock(return_value=httpx.Response(200, json=INFORMATION))

    async with httpx.AsyncClient() as http:
        with pytest.raises(httpx.HTTPStatusError):
            await VelovClient(http, CONFIGURED).fetch()


@respx.mock
async def test_timeout_propagates() -> None:
    respx.get(STATUS_URL).mock(side_effect=httpx.ConnectTimeout("trop lent"))
    respx.get(INFORMATION_URL).mock(return_value=httpx.Response(200, json=INFORMATION))

    async with httpx.AsyncClient() as http:
        with pytest.raises(httpx.ConnectTimeout):
            await VelovClient(http, CONFIGURED).fetch()


@respx.mock
async def test_malformed_payload_raises_validation_error() -> None:
    from pydantic import ValidationError

    respx.get(STATUS_URL).mock(return_value=httpx.Response(200, json={"unexpected": True}))
    respx.get(INFORMATION_URL).mock(return_value=httpx.Response(200, json=INFORMATION))

    async with httpx.AsyncClient() as http:
        with pytest.raises(ValidationError):
            await VelovClient(http, CONFIGURED).fetch()
