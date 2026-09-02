import os
from pathlib import Path

import httpx
import pytest

from eink_dashboard.core.config import load_dashboard_config
from eink_dashboard.providers.tcl.client import TclClient


@pytest.mark.network
async def test_live_tcl_returns_departures() -> None:
    username = os.environ["GRANDLYON_USERNAME"]
    password = os.environ["GRANDLYON_PASSWORD"]

    stops = load_dashboard_config(Path("config/dashboard.toml")).tcl_stops
    assert stops, "config/dashboard.toml doit contenir au moins un arrêt"

    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as http:
        snapshot = await TclClient(http, stops, username, password).fetch()

    boards = snapshot.data
    assert len(boards) == len(stops)
    assert all(board.available for board in boards)
    assert any(board.departures for board in boards)
