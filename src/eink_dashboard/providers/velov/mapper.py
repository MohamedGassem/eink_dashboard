from collections.abc import Sequence

from eink_dashboard.core.config import VelovStation
from eink_dashboard.domain.bikes import BikeStation
from eink_dashboard.providers.velov.schemas import StationInformationFeed, StationStatusFeed

MECHANICAL = "mechanical"
ELECTRICAL = "electrical"


def to_bike_stations(
    status: StationStatusFeed,
    information: StationInformationFeed,
    configured: Sequence[VelovStation],
) -> tuple[BikeStation, ...]:
    by_status = {station.station_id: station for station in status.data.stations}
    by_information = {station.station_id: station for station in information.data.stations}

    result: list[BikeStation] = []
    for wanted in configured:
        live = by_status.get(wanted.station_id)
        if live is None:
            continue
        counts = {entry.vehicle_type_id: entry.count for entry in live.vehicle_types_available}
        reference = by_information.get(wanted.station_id)
        result.append(
            BikeStation(
                station_id=wanted.station_id,
                label=wanted.label,
                bikes_available=live.num_vehicles_available,
                bikes_mechanical=counts.get(MECHANICAL, 0),
                bikes_electric=counts.get(ELECTRICAL, 0),
                docks_available=live.num_docks_available,
                capacity=reference.capacity if reference else 0,
                is_renting=live.is_renting and live.is_installed,
                reported_at=live.last_reported,
            )
        )
    return tuple(result)
