from pathlib import Path

import pytest
from pydantic import ValidationError

from eink_dashboard.core.config import (
    DashboardConfig,
    DirectionAlias,
    DisruptionLine,
    DisruptionsConfig,
    Settings,
    TclStop,
    VelovStation,
    WeatherConfig,
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


def test_load_dashboard_config_reads_v2_sections() -> None:
    config = load_dashboard_config(FIXTURES / "dashboard_ok.toml")

    assert config.alias_for("Saint-Priest Bel Air") == "St-Priest"
    assert config.alias_for("Gare de Vaise") == "Gare de Vaise"
    assert config.disruptions is not None
    assert config.disruptions.lines == ["T2", "D"]
    assert config.disruptions.ref_to_label() == {
        "ActIV:Line::T2:SYTRAL": "T2",
        "ActIV:Line::D:SYTRAL": "D",
    }
    assert config.weather is not None
    assert config.weather.lookahead_hours == 6
    assert config.weather.rain_probability_threshold == 50


def test_load_dashboard_config_stays_compatible_with_v1_toml(tmp_path: Path) -> None:
    v1 = tmp_path / "v1.toml"
    v1.write_text(
        '[[tcl.stops]]\nname = "A"\nstop_id = "1"\nlines = ["A"]\n'
        '[[velov.stations]]\nstation_id = "9"\nlabel = "Z"\n',
        encoding="utf-8",
    )

    config = load_dashboard_config(v1)

    assert config.direction_aliases == []
    assert config.disruptions is None
    assert config.weather is None


def test_weather_config_rejects_out_of_range_values() -> None:
    with pytest.raises(ValidationError):
        WeatherConfig(latitude=100.0, longitude=4.0)
    with pytest.raises(ValidationError):
        WeatherConfig(latitude=45.0, longitude=200.0)
    with pytest.raises(ValidationError):
        WeatherConfig(latitude=45.0, longitude=4.0, lookahead_hours=0)
    with pytest.raises(ValidationError):
        WeatherConfig(latitude=45.0, longitude=4.0, rain_probability_threshold=101)


def test_dashboard_config_rejects_conflicting_direction_aliases() -> None:
    with pytest.raises(ValidationError):
        DashboardConfig(
            direction_aliases=[
                DirectionAlias(match="Perrache", label="Perrache"),
                DirectionAlias(match="Perrache", label="Sud"),
            ]
        )
    # Même match, même label : toléré.
    DashboardConfig(
        direction_aliases=[
            DirectionAlias(match="Perrache", label="Perrache"),
            DirectionAlias(match="perrache", label="Perrache"),
        ]
    )


def test_disruptions_config_rejects_ref_mapped_to_two_labels() -> None:
    with pytest.raises(ValidationError):
        DisruptionsConfig(
            lines=["T2", "D"],
            line_refs=[
                DisruptionLine(label="T2", refs=["ActIV:Line::X:SYTRAL"]),
                DisruptionLine(label="D", refs=["ActIV:Line::X:SYTRAL"]),
            ],
        )


def test_runtime_requires_line_refs_for_followed_disruption_lines() -> None:
    monkey = Settings(_env_file=None, grandlyon_username="u", grandlyon_password="p")
    config = DashboardConfig(
        tcl_stops=[TclStop(name="A", stop_id="1", lines=["T2"])],
        disruptions=DisruptionsConfig(
            lines=["T2", "D"],
            line_refs=[DisruptionLine(label="T2", refs=["ActIV:Line::T2:SYTRAL"])],
        ),
    )

    with pytest.raises(ValueError, match="D"):
        validate_runtime_requirements(monkey, config, device_enabled=False)


def test_settings_read_v2_refresh_intervals(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TCL_DISRUPTIONS_REFRESH_SECONDS", "180")
    monkeypatch.setenv("WEATHER_REFRESH_SECONDS", "900")

    settings = Settings(_env_file=None)

    assert settings.tcl_disruptions_refresh_seconds == 180
    assert settings.weather_refresh_seconds == 900


@pytest.mark.parametrize("field", ["tcl_disruptions_refresh_seconds", "weather_refresh_seconds"])
def test_settings_reject_non_positive_v2_refresh_intervals(field: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: 0})


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
