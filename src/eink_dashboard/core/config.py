import re
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any, Self
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
    # Libellé de sens affiché pour cet arrêt. Sinon : alias de direction, sinon
    # destination du prochain passage. Un arrêt = un sens, donc une ligne à l'écran.
    label: str | None = Field(default=None, min_length=1)

    @field_validator("lines")
    @classmethod
    def validate_lines(cls, values: list[str]) -> list[str]:
        return _unique_non_empty(values, "lignes TCL")

    @field_validator("directions")
    @classmethod
    def validate_directions(cls, values: list[str]) -> list[str]:
        return _unique_non_empty(values, "directions TCL")


class DirectionAlias(BaseModel):
    match: str = Field(min_length=1)
    label: str = Field(min_length=1)


class DisruptionLine(BaseModel):
    """Associe un label interne (``T2``, ``D``) aux ``LineRef`` SIRI réels."""

    label: str = Field(min_length=1)
    refs: list[str] = Field(min_length=1)

    @field_validator("refs")
    @classmethod
    def validate_refs(cls, values: list[str]) -> list[str]:
        return _unique_non_empty(values, "LineRef SIRI")


class DisruptionsConfig(BaseModel):
    lines: list[str] = Field(default_factory=list)
    line_refs: list[DisruptionLine] = Field(default_factory=list)
    # Fenêtre au-delà de laquelle une perturbation planifiée future n'est pas encore affichée.
    future_window_hours: int = Field(default=2, ge=1)

    @field_validator("lines")
    @classmethod
    def validate_lines(cls, values: list[str]) -> list[str]:
        return _unique_non_empty(values, "lignes suivies")

    @model_validator(mode="after")
    def validate_refs_map_to_one_label(self) -> Self:
        seen: dict[str, str] = {}
        for entry in self.line_refs:
            for ref in entry.refs:
                previous = seen.get(ref)
                if previous is not None and previous != entry.label:
                    raise ValueError(
                        f"LineRef {ref!r} associé à deux labels internes: {previous!r} et "
                        f"{entry.label!r}"
                    )
                seen[ref] = entry.label
        return self

    def ref_to_label(self) -> dict[str, str]:
        return {ref: entry.label for entry in self.line_refs for ref in entry.refs}


class WeatherConfig(BaseModel):
    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)
    lookahead_hours: int = Field(default=6, ge=1)
    rain_probability_threshold: int = Field(default=50, ge=0, le=100)


class VelovStation(BaseModel):
    station_id: str = Field(min_length=1)
    label: str = Field(min_length=1)


class DashboardConfig(BaseModel):
    tcl_stops: list[TclStop] = Field(default_factory=list, max_length=MAX_TCL_STOPS)
    velov_stations: list[VelovStation] = Field(default_factory=list, max_length=MAX_VELOV_STATIONS)
    direction_aliases: list[DirectionAlias] = Field(default_factory=list)
    disruptions: DisruptionsConfig | None = None
    weather: WeatherConfig | None = None

    @model_validator(mode="after")
    def validate_unique_ids(self) -> Self:
        _unique_non_empty([stop.stop_id for stop in self.tcl_stops], "IDs d'arrêt TCL")
        _unique_non_empty(
            [station.station_id for station in self.velov_stations], "IDs de station Vélo'v"
        )
        return self

    @model_validator(mode="after")
    def validate_direction_aliases(self) -> Self:
        seen: dict[str, str] = {}
        for alias in self.direction_aliases:
            key = alias.match.strip().casefold()
            previous = seen.get(key)
            if previous is not None and previous != alias.label:
                raise ValueError(
                    f"alias de direction {alias.match!r} associé à deux labels: {previous!r} et "
                    f"{alias.label!r}"
                )
            seen[key] = alias.label
        return self

    def alias_for(self, direction: str) -> str:
        haystack = direction.casefold()
        for alias in self.direction_aliases:
            if alias.match.casefold() in haystack:
                return alias.label
        return direction


def load_dashboard_config(path: Path) -> DashboardConfig:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    tcl = raw.get("tcl", {})
    disruptions_raw: dict[str, Any] | None = tcl.get("disruptions")
    return DashboardConfig(
        tcl_stops=tcl.get("stops", []),
        velov_stations=raw.get("velov", {}).get("stations", []),
        direction_aliases=tcl.get("direction_aliases", []),
        disruptions=DisruptionsConfig(**disruptions_raw) if disruptions_raw is not None else None,
        weather=WeatherConfig(**raw["weather"]) if "weather" in raw else None,
    )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    grandlyon_username: str = ""
    grandlyon_password: str = ""
    device_mac: str = ""
    device_api_key: str = ""
    public_base_url: str = "http://localhost:9001"
    tz: str = "Europe/Paris"
    log_level: str = "INFO"
    tcl_refresh_seconds: int = Field(default=60, gt=0)
    velov_refresh_seconds: int = Field(default=60, gt=0)
    tcl_disruptions_refresh_seconds: int = Field(default=120, gt=0)
    weather_refresh_seconds: int = Field(default=600, gt=0)
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
    if config.disruptions is not None and config.disruptions.lines:
        mapped = {entry.label for entry in config.disruptions.line_refs}
        unmapped = [line for line in config.disruptions.lines if line not in mapped]
        if unmapped:
            raise ValueError(
                "perturbations: lignes suivies sans LineRef configuré: " + ", ".join(unmapped)
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
