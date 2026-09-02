from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Departure:
    line: str
    direction: str
    expected_at: datetime
    is_realtime: bool

    def minutes_until(self, now: datetime) -> int:
        delta = (self.expected_at - now).total_seconds()
        return max(0, int(delta // 60))


@dataclass(frozen=True, slots=True)
class StopBoard:
    stop_name: str
    departures: tuple[Departure, ...]
