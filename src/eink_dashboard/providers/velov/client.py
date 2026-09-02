import time
from collections.abc import Sequence

import httpx

from eink_dashboard.core.config import VelovStation
from eink_dashboard.domain.bikes import BikeStation
from eink_dashboard.providers.base import ProviderError, ProviderSnapshot
from eink_dashboard.providers.velov.mapper import to_bike_stations
from eink_dashboard.providers.velov.schemas import StationInformationFeed, StationStatusFeed

BASE = "https://api.cyclocity.fr/contracts/lyon/gbfs/v3"
STATUS_URL = f"{BASE}/station_status.json"
INFORMATION_URL = f"{BASE}/station_information.json"


class VelovClient:
    name = "velov"

    def __init__(
        self,
        http: httpx.AsyncClient,
        stations: Sequence[VelovStation],
        interval: float = 60.0,
        information_ttl: float = 3600.0,
    ) -> None:
        self._http = http
        self._stations = stations
        self.interval = interval
        self._information_ttl = information_ttl
        self._information: StationInformationFeed | None = None
        self._information_fetched_at = 0.0

    async def _information_feed(self) -> StationInformationFeed:
        now = time.monotonic()
        cached = self._information
        if cached is not None and now - self._information_fetched_at < self._information_ttl:
            return cached
        response = await self._http.get(INFORMATION_URL)
        response.raise_for_status()
        feed = StationInformationFeed.model_validate_json(response.content)
        self._information = feed
        self._information_fetched_at = now
        return feed

    async def fetch(self) -> ProviderSnapshot[tuple[BikeStation, ...]]:
        information = await self._information_feed()
        response = await self._http.get(STATUS_URL)
        response.raise_for_status()
        status = StationStatusFeed.model_validate_json(response.content)
        stations = to_bike_stations(status, information, self._stations)
        returned_ids = {station.station_id for station in stations}
        missing_ids = [
            station.station_id
            for station in self._stations
            if station.station_id not in returned_ids
        ]
        if missing_ids:
            raise ProviderError(f"stations Vélo'v absentes du statut: {', '.join(missing_ids)}")
        source_updated_at = min(
            (station.reported_at for station in stations), default=status.last_updated
        )
        return ProviderSnapshot(data=stations, source_updated_at=source_updated_at)
