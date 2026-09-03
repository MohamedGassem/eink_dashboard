from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from eink_dashboard.core.config import DisruptionsConfig
from eink_dashboard.domain.disruptions import TransitDisruption
from eink_dashboard.providers.base import ProviderSnapshot
from eink_dashboard.providers.tcl_sx.mapper import to_disruptions
from eink_dashboard.providers.tcl_sx.schemas import SiriDocument

SITUATION_EXCHANGE_URL = "https://data.grandlyon.com/siri-lite/2.0/situation-exchange.json"


class TclDisruptionsClient:
    name = "tcl_disruptions"

    def __init__(
        self,
        http: httpx.AsyncClient,
        config: DisruptionsConfig,
        username: str,
        password: str,
        tz: ZoneInfo,
        interval: float = 120.0,
    ) -> None:
        self._http = http
        self._config = config
        self._auth = httpx.BasicAuth(username, password)
        self._tz = tz
        self.interval = interval

    async def fetch(self) -> ProviderSnapshot[tuple[TransitDisruption, ...]]:
        response = await self._http.get(SITUATION_EXCHANGE_URL, auth=self._auth)
        response.raise_for_status()
        document = SiriDocument.model_validate_json(response.content)
        disruptions = to_disruptions(document, self._config, datetime.now(self._tz))
        return ProviderSnapshot(data=disruptions, source_updated_at=None)
