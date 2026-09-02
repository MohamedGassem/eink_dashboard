import re
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MAX_TCL_STOPS = 2
MAX_LINES_PER_STOP = 2
MAX_DIRECTIONS_PER_STOP = 2
MAX_VELOV_STATIONS = 2


def _unique_non_empty(values: list[str], label: str) -> list[str]:
    normalized = [value.strip().casefold() for value in values]
    if any(not value for value in normalized):
        raise ValueError(f"{label}: les valeurs vides sont interdites")
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{label}: les valeurs doivent être uniques")
    return values


class TclStop(BaseModel):
    name: str = Field(min_length=1)
    stop_id: str = Field(min_length=1)
    lines: list[str] = Field(min_length=1, max_length=MAX_LINES_PER_STOP)
    directions: list[str] = Field(default_factory=list, max_length=MAX_DIRECTIONS_PER_STOP)

    @field_validator("lines")
    @classmethod
    def validate_lines(cls, values: list[str]) -> list[str]:
        return _unique_non_empty(values, "lignes TCL")

    @field_validator("directions")
    @classmethod
    def validate_directions(cls, values: list[str]) -> list[str]:
        return _unique_non_empty(values, "directions TCL")


class VelovStation(BaseModel):
    station_id: str = Field(min_length=1)
    label: str = Field(min_length=1)


class DashboardConfig(BaseModel):
    tcl_stops: list[TclStop] = Field(default_factory=list, max_length=MAX_TCL_STOPS)
    velov_stations: list[VelovStation] = Field(default_factory=list, max_length=MAX_VELOV_STATIONS)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> Self:
        _unique_non_empty([stop.stop_id for stop in self.tcl_stops], "IDs d'arrêt TCL")
        _unique_non_empty(
            [station.station_id for station in self.velov_stations], "IDs de station Vélo'v"
        )
        return self


def load_dashboard_config(path: Path) -> DashboardConfig:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    return DashboardConfig(
        tcl_stops=raw.get("tcl", {}).get("stops", []),
        velov_stations=raw.get("velov", {}).get("stations", []),
    )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    grandlyon_username: str = ""
    grandlyon_password: str = ""
    device_mac: str = ""
    device_api_key: str = ""
    public_base_url: str = "http://localhost:8000"
    tz: str = "Europe/Paris"
    log_level: str = "INFO"
    tcl_refresh_seconds: int = Field(default=60, gt=0)
    velov_refresh_seconds: int = Field(default=60, gt=0)
    config_path: Path = Path("config/dashboard.toml")

    @field_validator("tz")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(f"fuseau horaire inconnu: {value}") from error
        return value

    @field_validator("device_mac")
    @classmethod
    def validate_device_mac(cls, value: str) -> str:
        if value and re.fullmatch(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", value) is None:
            raise ValueError("DEVICE_MAC doit être une adresse MAC séparée par des deux-points")
        return value


def validate_runtime_requirements(
    settings: Settings, config: DashboardConfig, *, device_enabled: bool
) -> None:
    missing: list[str] = []
    if config.tcl_stops:
        if not settings.grandlyon_username.strip():
            missing.append("GRANDLYON_USERNAME")
        if not settings.grandlyon_password.strip():
            missing.append("GRANDLYON_PASSWORD")
    if device_enabled:
        if not settings.device_mac.strip():
            missing.append("DEVICE_MAC")
        if not settings.device_api_key.strip():
            missing.append("DEVICE_API_KEY")
    if missing:
        names = ", ".join(missing)
        raise ValueError(f"configuration runtime incomplète: {names}")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
