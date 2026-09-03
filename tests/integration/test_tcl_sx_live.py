import os
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from eink_dashboard.core.config import load_dashboard_config
from eink_dashboard.providers.tcl_sx.client import SITUATION_EXCHANGE_URL
from eink_dashboard.providers.tcl_sx.mapper import to_disruptions
from eink_dashboard.providers.tcl_sx.schemas import SiriDocument


@pytest.mark.network
async def test_live_situation_exchange_is_parseable() -> None:
    username = os.environ["GRANDLYON_USERNAME"]
    password = os.environ["GRANDLYON_PASSWORD"]

    config = load_dashboard_config(Path("config/dashboard.toml")).disruptions
    assert config is not None, "config/dashboard.toml doit contenir [tcl.disruptions]"

    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as http:
        response = await http.get(SITUATION_EXCHANGE_URL, auth=httpx.BasicAuth(username, password))
    response.raise_for_status()

    document = SiriDocument.model_validate_json(response.content)
    assert document.situations(), "le flux SIRI-SX doit contenir des PtSituationElement"

    # Ne doit pas lever, quel que soit l'état du réseau au moment du test.
    disruptions = to_disruptions(document, config, datetime.now(UTC))
    for entry in disruptions:
        assert entry.lines
        assert entry.description
