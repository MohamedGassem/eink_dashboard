from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from eink_dashboard.core.config import WeatherConfig
from eink_dashboard.domain.weather import WeatherSnapshot
from eink_dashboard.providers.base import ProviderSnapshot
from eink_dashboard.providers.weather.mapper import to_weather_snapshot
from eink_dashboard.providers.weather.schemas import ForecastFeed

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


class WeatherClient:
    name = "weather"

    def __init__(
        self,
        http: httpx.AsyncClient,
        config: WeatherConfig,
        tz: ZoneInfo,
        interval: float = 600.0,
    ) -> None:
        self._http = http
        self._config = config
        self._tz = tz
        self.interval = interval

    async def fetch(self) -> ProviderSnapshot[WeatherSnapshot]:
        response = await self._http.get(
            FORECAST_URL,
            params={
                "latitude": self._config.latitude,
                "longitude": self._config.longitude,
                "current": "temperature_2m",
                "hourly": "precipitation_probability,precipitation",
                "timezone": str(self._tz),
                "forecast_days": 2,
            },
        )
        response.raise_for_status()
        feed = ForecastFeed.model_validate_json(response.content)
        snapshot = to_weather_snapshot(feed, self._config, datetime.now(self._tz), self._tz)
        return ProviderSnapshot(data=snapshot, source_updated_at=snapshot.reported_at)
