import base64
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx

from eink_dashboard.core.config import DisruptionLine, DisruptionsConfig
from eink_dashboard.providers.tcl_sx.client import SITUATION_EXCHANGE_URL, TclDisruptionsClient

PARIS = ZoneInfo("Europe/Paris")
CONFIG = DisruptionsConfig(
    lines=["T2", "D"],
    line_refs=[
        DisruptionLine(label="T2", refs=["ActIV:Line::T2:SYTRAL"]),
        DisruptionLine(label="D", refs=["ActIV:Line::D:SYTRAL"]),
    ],
)

EMPTY_BODY = {"Siri": {"ServiceDelivery": {"SituationExchangeDelivery": []}}}

D_REF = "ActIV:Line::D:SYTRAL"


def _body(*line_refs: str) -> dict:
    affected = [{"LineRef": {"value": ref}} for ref in line_refs]
    element = {
        "SituationNumber": {"value": "S1"},
        "ValidityPeriod": [{"StartTime": "2000-01-01T00:00:00Z"}],
        "Description": [{"value": "Ligne D perturbée."}],
        "Consequences": {
            "Consequence": [
                {"Affects": {"Networks": {"AffectedNetwork": [{"AffectedLine": affected}]}}}
            ]
        },
    }
    return {
        "Siri": {
            "ServiceDelivery": {
                "SituationExchangeDelivery": [{"Situations": {"PtSituationElement": [element]}}]
            }
        }
    }


D_BODY = _body(D_REF)


def _client(http: httpx.AsyncClient) -> TclDisruptionsClient:
    return TclDisruptionsClient(http, CONFIG, username="alice", password="secret", tz=PARIS)


@respx.mock
async def test_fetch_maps_situation_exchange_body() -> None:
    respx.get(SITUATION_EXCHANGE_URL).mock(return_value=httpx.Response(200, json=D_BODY))

    async with httpx.AsyncClient() as http:
        snapshot = await _client(http).fetch()

    assert [d.lines for d in snapshot.data] == [("D",)]


@respx.mock
async def test_fetch_sends_basic_authentication() -> None:
    route = respx.get(SITUATION_EXCHANGE_URL).mock(
        return_value=httpx.Response(200, json=EMPTY_BODY)
    )

    async with httpx.AsyncClient() as http:
        await _client(http).fetch()

    expected = base64.b64encode(b"alice:secret").decode()
    assert route.calls[0].request.headers["authorization"] == f"Basic {expected}"


@respx.mock
async def test_empty_but_valid_body_yields_no_disruptions() -> None:
    respx.get(SITUATION_EXCHANGE_URL).mock(return_value=httpx.Response(200, json=EMPTY_BODY))

    async with httpx.AsyncClient() as http:
        snapshot = await _client(http).fetch()

    assert snapshot.data == ()


@respx.mock
async def test_unauthorized_propagates_to_the_scheduler() -> None:
    respx.get(SITUATION_EXCHANGE_URL).mock(return_value=httpx.Response(401))

    async with httpx.AsyncClient() as http:
        with pytest.raises(httpx.HTTPStatusError):
            await _client(http).fetch()


@respx.mock
async def test_timeout_propagates_to_the_scheduler() -> None:
    respx.get(SITUATION_EXCHANGE_URL).mock(side_effect=httpx.ReadTimeout("trop lent"))

    async with httpx.AsyncClient() as http:
        with pytest.raises(httpx.ReadTimeout):
            await _client(http).fetch()
