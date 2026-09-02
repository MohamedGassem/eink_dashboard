import base64

import httpx
import pytest
import respx
from pydantic import ValidationError

from eink_dashboard.core.config import TclStop
from eink_dashboard.providers.base import ProviderError
from eink_dashboard.providers.tcl.client import PASSAGES_URL, TclClient

STOPS = [TclStop(name="Bellecour", stop_id="1234", lines=["A"])]


def payload(stop_id: str = "1234") -> dict[str, object]:
    return {
        "nb_results": 1,
        "values": [
            {
                "id": int(stop_id),
                "ligne": "A",
                "direction": "Vaulx-en-Velin La Soie",
                "heurepassage": "2026-09-02 08:05:00",
                "type": "E",
            }
        ],
    }


def client(http: httpx.AsyncClient) -> TclClient:
    return TclClient(http, STOPS, username="alice", password="secret")


@respx.mock
async def test_fetch_returns_one_board_per_configured_stop() -> None:
    respx.get(PASSAGES_URL).mock(return_value=httpx.Response(200, json=payload()))

    async with httpx.AsyncClient() as http:
        snapshot = await client(http).fetch()

    boards = snapshot.data
    assert len(boards) == 1
    assert boards[0].stop_name == "Bellecour"
    assert boards[0].available is True
    assert boards[0].departures[0].line == "A"
    assert boards[0].departures[0].is_realtime is True


@respx.mock
async def test_fetch_sends_basic_authentication() -> None:
    route = respx.get(PASSAGES_URL).mock(return_value=httpx.Response(200, json=payload()))

    async with httpx.AsyncClient() as http:
        await client(http).fetch()

    expected = base64.b64encode(b"alice:secret").decode()
    assert route.calls[0].request.headers["authorization"] == f"Basic {expected}"


@respx.mock
async def test_fetch_filters_on_the_configured_stop_id() -> None:
    route = respx.get(PASSAGES_URL).mock(return_value=httpx.Response(200, json=payload()))

    async with httpx.AsyncClient() as http:
        await client(http).fetch()

    assert "1234" in str(route.calls[0].request.url)


@respx.mock
async def test_unauthorized_raises_provider_error() -> None:
    respx.get(PASSAGES_URL).mock(return_value=httpx.Response(401, json={"detail": "non fourni"}))

    async with httpx.AsyncClient() as http:
        with pytest.raises(ProviderError):
            await client(http).fetch()


@respx.mock
async def test_timeout_raises_provider_error() -> None:
    respx.get(PASSAGES_URL).mock(side_effect=httpx.ReadTimeout("trop lent"))

    async with httpx.AsyncClient() as http:
        with pytest.raises(ProviderError):
            await client(http).fetch()


@respx.mock
async def test_changed_payload_shape_raises_provider_error() -> None:
    respx.get(PASSAGES_URL).mock(
        return_value=httpx.Response(200, json={"nb_results": 1, "values": [{"surprise": 1}]})
    )

    async with httpx.AsyncClient() as http:
        with pytest.raises(ProviderError):
            await client(http).fetch()


@respx.mock
async def test_one_failing_stop_does_not_hide_the_others() -> None:
    stops = [
        TclStop(name="Bellecour", stop_id="1234", lines=["A"]),
        TclStop(name="Part-Dieu", stop_id="5678", lines=["B"]),
    ]
    respx.get(PASSAGES_URL, params={"value": "1234"}).mock(
        return_value=httpx.Response(200, json=payload("1234"))
    )
    respx.get(PASSAGES_URL, params={"value": "5678"}).mock(return_value=httpx.Response(500))

    async with httpx.AsyncClient() as http:
        snapshot = await TclClient(http, stops, username="a", password="b").fetch()

    boards = snapshot.data
    assert [board.stop_name for board in boards] == ["Bellecour", "Part-Dieu"]
    assert boards[0].available is True
    assert boards[1].available is False
    assert boards[1].departures == ()


@respx.mock
async def test_malformed_payload_on_one_stop_is_isolated() -> None:
    stops = [
        TclStop(name="Bellecour", stop_id="1234", lines=["A"]),
        TclStop(name="Part-Dieu", stop_id="5678", lines=["B"]),
    ]
    respx.get(PASSAGES_URL, params={"value": "1234"}).mock(
        return_value=httpx.Response(200, json=payload("1234"))
    )
    respx.get(PASSAGES_URL, params={"value": "5678"}).mock(
        return_value=httpx.Response(200, json={"values": [{"surprise": 1}]})
    )

    async with httpx.AsyncClient() as http:
        snapshot = await TclClient(http, stops, username="a", password="b").fetch()

    assert snapshot.data[1].available is False


@respx.mock
async def test_provider_error_names_every_failing_stop() -> None:
    respx.get(PASSAGES_URL).mock(return_value=httpx.Response(503))

    async with httpx.AsyncClient() as http:
        with pytest.raises(ProviderError, match="Bellecour"):
            await client(http).fetch()


def test_schema_error_is_raised_for_bad_payload() -> None:
    with pytest.raises(ValidationError):
        from eink_dashboard.providers.tcl.schemas import PassageFeed

        PassageFeed.model_validate({"values": [{"surprise": 1}]})
