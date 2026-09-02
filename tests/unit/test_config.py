from pathlib import Path

import pytest
from pydantic import ValidationError

from eink_dashboard.core.config import (
    DashboardConfig,
    Settings,
    TclStop,
    VelovStation,
    load_dashboard_config,
    validate_runtime_requirements,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_load_dashboard_config_reads_stops_and_stations() -> None:
    config = load_dashboard_config(FIXTURES / "dashboard_ok.toml")

    assert [stop.name for stop in config.tcl_stops] == ["Bellecour", "Part-Dieu"]
    assert config.tcl_stops[0].lines == ["A", "D"]
    assert config.tcl_stops[1].directions == []
    assert [station.station_id for station in config.velov_stations] == ["1032", "1024"]


def test_load_dashboard_config_rejects_missing_stop_id(tmp_path: Path) -> None:
    bad = tmp_path / "bad.toml"
    bad.write_text('[[tcl.stops]]\nname = "Sans identifiant"\n', encoding="utf-8")

    with pytest.raises(ValidationError):
        load_dashboard_config(bad)


def test_load_dashboard_config_accepts_empty_file(tmp_path: Path) -> None:
    empty = tmp_path / "empty.toml"
    empty.write_text("", encoding="utf-8")

    config = load_dashboard_config(empty)

    assert config.tcl_stops == []
    assert config.velov_stations == []


def test_settings_read_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRANDLYON_USERNAME", "alice")
    monkeypatch.setenv("TCL_REFRESH_SECONDS", "90")

    settings = Settings(_env_file=None)

    assert settings.grandlyon_username == "alice"
    assert settings.tcl_refresh_seconds == 90
    assert settings.velov_refresh_seconds == 60


@pytest.mark.parametrize("field", ["tcl_refresh_seconds", "velov_refresh_seconds"])
def test_settings_reject_non_positive_refresh_intervals(field: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: 0})


def test_settings_reject_unknown_timezone() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, tz="Mars/Olympus_Mons")


def test_settings_reject_invalid_non_empty_device_mac() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, device_mac="not-a-mac")


def test_dashboard_config_rejects_duplicate_provider_ids() -> None:
    with pytest.raises(ValidationError):
        DashboardConfig(
            tcl_stops=[
                TclStop(name="A", stop_id="same", lines=["A"]),
                TclStop(name="B", stop_id="same", lines=["B"]),
            ]
        )

    with pytest.raises(ValidationError):
        DashboardConfig(
            velov_stations=[
                VelovStation(station_id="same", label="A"),
                VelovStation(station_id="same", label="B"),
            ]
        )


def test_dashboard_config_rejects_content_beyond_v1_layout() -> None:
    with pytest.raises(ValidationError):
        DashboardConfig(
            tcl_stops=[
                TclStop(name=str(index), stop_id=str(index), lines=["A"]) for index in range(3)
            ]
        )

    with pytest.raises(ValidationError):
        TclStop(name="Trop de lignes", stop_id="1", lines=["A", "B", "C"])

    with pytest.raises(ValidationError):
        DashboardConfig(
            velov_stations=[
                VelovStation(station_id=str(index), label=str(index)) for index in range(3)
            ]
        )


def test_runtime_requires_tcl_credentials_only_when_tcl_is_configured() -> None:
    settings = Settings(_env_file=None)
    config = DashboardConfig(tcl_stops=[TclStop(name="Bellecour", stop_id="1", lines=["A"])])

    with pytest.raises(ValueError, match="GRANDLYON_USERNAME"):
        validate_runtime_requirements(settings, config, device_enabled=False)

    validate_runtime_requirements(settings, DashboardConfig(), device_enabled=False)


def test_runtime_requires_device_identity_when_device_api_is_enabled() -> None:
    with pytest.raises(ValueError, match="DEVICE_MAC"):
        validate_runtime_requirements(
            Settings(_env_file=None), DashboardConfig(), device_enabled=True
        )
