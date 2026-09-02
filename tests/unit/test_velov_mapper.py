from pathlib import Path

from eink_dashboard.core.config import VelovStation
from eink_dashboard.providers.velov.mapper import to_bike_stations
from eink_dashboard.providers.velov.schemas import StationInformationFeed, StationStatusFeed

FIXTURES = Path(__file__).parent.parent / "fixtures"


def load_status() -> StationStatusFeed:
    return StationStatusFeed.model_validate_json(
        (FIXTURES / "velov_station_status.json").read_text(encoding="utf-8")
    )


def load_information() -> StationInformationFeed:
    return StationInformationFeed.model_validate_json(
        (FIXTURES / "velov_station_information.json").read_text(encoding="utf-8")
    )


CONFIGURED = [
    VelovStation(station_id="1032", label="Pizay"),
    VelovStation(station_id="1024", label="Rouville"),
]


def test_schemas_parse_real_payloads() -> None:
    assert len(load_status().data.stations) == 3
    assert len(load_information().data.stations) == 2


def test_mapper_keeps_configured_order() -> None:
    stations = to_bike_stations(load_status(), load_information(), CONFIGURED)
    assert [station.station_id for station in stations] == ["1032", "1024"]


def test_mapper_uses_configured_label_not_provider_name() -> None:
    stations = to_bike_stations(load_status(), load_information(), CONFIGURED)
    assert stations[0].label == "Pizay"


def test_mapper_splits_mechanical_and_electric() -> None:
    stations = to_bike_stations(load_status(), load_information(), CONFIGURED)
    assert stations[0].bikes_mechanical == 8
    assert stations[0].bikes_electric == 4
    assert stations[0].bikes_available == 12


def test_mapper_reads_capacity_from_information_feed() -> None:
    stations = to_bike_stations(load_status(), load_information(), CONFIGURED)
    assert stations[0].capacity == 20
    assert stations[1].capacity == 17


def test_mapper_skips_station_absent_from_status() -> None:
    configured = [*CONFIGURED, VelovStation(station_id="9999", label="Fantome")]
    stations = to_bike_stations(load_status(), load_information(), configured)
    assert [station.station_id for station in stations] == ["1032", "1024"]


def test_mapper_falls_back_to_zero_capacity_when_information_missing() -> None:
    information = load_information()
    information.data.stations = [
        station for station in information.data.stations if station.station_id != "1024"
    ]
    stations = to_bike_stations(load_status(), information, CONFIGURED)
    assert stations[1].capacity == 0


def test_mapper_reports_out_of_service_station() -> None:
    configured = [VelovStation(station_id="1", label="Hors service")]
    stations = to_bike_stations(load_status(), load_information(), configured)
    assert stations[0].is_renting is False
