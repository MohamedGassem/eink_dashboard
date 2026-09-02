from pathlib import Path

import pytest
from pydantic import ValidationError

from eink_dashboard.core.config import Settings, load_dashboard_config

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
