from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from eink_dashboard.core.config import WeatherConfig
from eink_dashboard.providers.weather.mapper import to_weather_snapshot
from eink_dashboard.providers.weather.schemas import ForecastFeed

FIXTURES = Path(__file__).parent.parent / "fixtures"
PARIS = ZoneInfo("Europe/Paris")
NOW = datetime(2026, 9, 3, 13, 30, tzinfo=PARIS)


def _feed() -> ForecastFeed:
    return ForecastFeed.model_validate_json(
        (FIXTURES / "open_meteo_forecast.json").read_text(encoding="utf-8")
    )


def _config(**kwargs: object) -> WeatherConfig:
    base: dict[str, object] = {"latitude": 45.75, "longitude": 4.85}
    base.update(kwargs)
    return WeatherConfig(**base)


def test_current_temperature_is_read() -> None:
    snapshot = to_weather_snapshot(_feed(), _config(), NOW, PARIS)
    assert snapshot.temperature_c == 18.3
    assert snapshot.reported_at == datetime(2026, 9, 3, 13, 30, tzinfo=PARIS)


def test_first_actionable_rain_is_returned() -> None:
    snapshot = to_weather_snapshot(_feed(), _config(lookahead_hours=6), NOW, PARIS)
    assert snapshot.rain_at == datetime(2026, 9, 3, 15, 0, tzinfo=PARIS)


def test_no_rain_when_lookahead_is_too_short() -> None:
    snapshot = to_weather_snapshot(_feed(), _config(lookahead_hours=1), NOW, PARIS)
    assert snapshot.rain_at is None


def test_probability_below_threshold_is_not_rain() -> None:
    # 16:00 a de la pluie (0.4 mm) mais seulement 30 % de probabilité.
    snapshot = to_weather_snapshot(
        _feed(), _config(lookahead_hours=6, rain_probability_threshold=75), NOW, PARIS
    )
    # 14:00 : 80 % mais 0 mm ; 15:00 : 70 % < 75 ; 18:00 : 90 % et 1.2 mm.
    assert snapshot.rain_at == datetime(2026, 9, 3, 18, 0, tzinfo=PARIS)


def test_high_probability_without_precipitation_is_not_rain() -> None:
    # 14:00 : 80 % de probabilité mais 0 mm -> ignoré, 15:00 retenu.
    snapshot = to_weather_snapshot(_feed(), _config(lookahead_hours=6), NOW, PARIS)
    assert snapshot.rain_at != datetime(2026, 9, 3, 14, 0, tzinfo=PARIS)


def test_rain_time_is_timezone_aware() -> None:
    snapshot = to_weather_snapshot(_feed(), _config(), NOW, PARIS)
    assert snapshot.rain_at is not None
    assert snapshot.rain_at.tzinfo is not None


def test_malformed_payload_raises() -> None:
    with pytest.raises(ValidationError):
        ForecastFeed.model_validate({"current": {"time": "2026-09-03T13:30"}})
