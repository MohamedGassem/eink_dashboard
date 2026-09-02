from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class BikeStation:
    station_id: str
    label: str
    bikes_available: int
    bikes_mechanical: int
    bikes_electric: int
    docks_available: int
    capacity: int
    is_renting: bool
    reported_at: datetime
