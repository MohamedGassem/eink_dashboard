import tomllib
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class TclStop(BaseModel):
    name: str
    stop_id: str
    lines: list[str] = Field(default_factory=list)
    directions: list[str] = Field(default_factory=list)


class VelovStation(BaseModel):
    station_id: str
    label: str


class DashboardConfig(BaseModel):
    tcl_stops: list[TclStop] = Field(default_factory=list)
    velov_stations: list[VelovStation] = Field(default_factory=list)


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
    tcl_refresh_seconds: int = 60
    velov_refresh_seconds: int = 60
    config_path: Path = Path("config/dashboard.toml")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
