"""Open-Meteo brut -> `WeatherSnapshot`. Le domaine ignore le schéma externe."""

from datetime import datetime, timedelta, tzinfo

from eink_dashboard.core.config import WeatherConfig
from eink_dashboard.domain.weather import WeatherSnapshot
from eink_dashboard.providers.weather.schemas import ForecastFeed


def _parse_local(value: str, tz: tzinfo) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=tz)


def _first_rain(
    feed: ForecastFeed, config: WeatherConfig, now: datetime, tz: tzinfo
) -> datetime | None:
    hourly = feed.hourly
    horizon = now + timedelta(hours=config.lookahead_hours)
    current_hour = now.replace(minute=0, second=0, microsecond=0)

    for index, raw_time in enumerate(hourly.time):
        moment = _parse_local(raw_time, tz)
        if moment < current_hour or moment > horizon:
            continue
        probability = _at(hourly.precipitation_probability, index)
        millimetres = _at(hourly.precipitation, index)
        if probability >= config.rain_probability_threshold and millimetres > 0:
            return moment
    return None


def _at(values: list[int | None] | list[float | None], index: int) -> float:
    if index >= len(values):
        return 0.0
    value = values[index]
    return float(value) if value is not None else 0.0


def to_weather_snapshot(
    feed: ForecastFeed, config: WeatherConfig, now: datetime, tz: tzinfo
) -> WeatherSnapshot:
    return WeatherSnapshot(
        temperature_c=feed.current.temperature_2m,
        rain_at=_first_rain(feed, config, now, tz),
        reported_at=_parse_local(feed.current.time, tz),
    )
