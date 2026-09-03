"""Modèle permissif de la réponse Open-Meteo `/v1/forecast`.

Avec `timezone=Europe/Paris`, les `time` sont des ISO 8601 **naïfs** en heure
locale. Le mapper leur rattache le fuseau.
"""

from pydantic import BaseModel, ConfigDict

_CONFIG = ConfigDict(extra="ignore")


class CurrentWeather(BaseModel):
    model_config = _CONFIG

    time: str
    temperature_2m: float


class HourlyWeather(BaseModel):
    model_config = _CONFIG

    time: list[str]
    precipitation_probability: list[int | None] = []
    precipitation: list[float | None] = []


class ForecastFeed(BaseModel):
    model_config = _CONFIG

    current: CurrentWeather
    hourly: HourlyWeather
