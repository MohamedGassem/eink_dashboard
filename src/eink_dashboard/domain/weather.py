from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class WeatherSnapshot:
    temperature_c: float
    rain_at: datetime | None
    reported_at: datetime
