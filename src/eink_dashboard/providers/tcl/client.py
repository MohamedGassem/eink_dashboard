import asyncio
from collections.abc import Sequence

import httpx
import structlog

from eink_dashboard.core.config import TclStop
from eink_dashboard.domain.transit import StopBoard
from eink_dashboard.providers.base import ProviderError, ProviderSnapshot
from eink_dashboard.providers.tcl.mapper import to_stop_boards
from eink_dashboard.providers.tcl.schemas import TCL_FIELDS, PassageFeed

PASSAGES_URL = "https://download.data.grandlyon.com/ws/rdata/tcl_sytral.tclpassagearret/all.json"

log = structlog.get_logger()


class TclClient:
    name = "tcl"

    def __init__(
        self,
        http: httpx.AsyncClient,
        stops: Sequence[TclStop],
        username: str,
        password: str,
        interval: float = 60.0,
    ) -> None:
        self._http = http
        self._stops = stops
        self._auth = httpx.BasicAuth(username, password)
        self.interval = interval

    async def _board(self, stop: TclStop) -> StopBoard:
        response = await self._http.get(
            PASSAGES_URL,
            auth=self._auth,
            params={
                "field": TCL_FIELDS["stop_id"],
                "value": stop.stop_id,
                "maxfeatures": 40,
            },
        )
        response.raise_for_status()
        feed = PassageFeed.model_validate_json(response.content)
        return to_stop_boards(feed, stop)

    async def fetch(self) -> ProviderSnapshot[tuple[StopBoard, ...]]:
        results = await asyncio.gather(
            *(self._board(stop) for stop in self._stops), return_exceptions=True
        )
        boards: list[StopBoard] = []
        failures: list[str] = []
        for stop, result in zip(self._stops, results, strict=True):
            if isinstance(result, StopBoard):
                boards.append(result)
                continue
            if isinstance(result, BaseException) and not isinstance(result, Exception):
                raise result
            failures.append(stop.name)
            log.warning("tcl.stop_failed", stop=stop.name, error=str(result))
            boards.append(StopBoard(stop_name=stop.name, departures=(), available=False))

        if self._stops and len(failures) == len(self._stops):
            raise ProviderError(f"aucun arrêt TCL joignable: {', '.join(failures)}")
        return ProviderSnapshot(data=tuple(boards), source_updated_at=None)
