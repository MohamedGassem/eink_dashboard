import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from eink_dashboard.state import DashboardState

MAX_WAIT_MINUTES = 60
# status_at renvoie l'un de ok / degraded / stale / unavailable ; tout sauf ok
# vaut « données à ne pas prendre au pied de la lettre » côté affichage.
STALE_STATUSES = {"degraded", "stale", "unavailable"}


def format_wait(minutes: int) -> str:
    if minutes <= 0:
        return "à quai"
    if minutes > MAX_WAIT_MINUTES:
        return f"+{MAX_WAIT_MINUTES} min"
    return f"{minutes} min"


@dataclass(frozen=True, slots=True)
class DepartureLine:
    line: str
    direction: str
    waits: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StopBlock:
    title: str
    lines: tuple[DepartureLine, ...]
    stale: bool
    note: str


@dataclass(frozen=True, slots=True)
class BikeBlock:
    label: str
    bikes: int
    docks: int
    capacity: int | None
    stale: bool
    note: str


@dataclass(frozen=True, slots=True)
class DashboardView:
    as_of: str
    stops: tuple[StopBlock, ...]
    bikes: tuple[BikeBlock, ...]

    def content_hash(self) -> str:
        payload = json.dumps(
            {
                "stops": [
                    [
                        block.title,
                        block.stale,
                        block.note,
                        [[line.line, line.direction, list(line.waits)] for line in block.lines],
                    ]
                    for block in self.stops
                ],
                "bikes": [
                    [block.label, block.bikes, block.docks, block.capacity, block.stale, block.note]
                    for block in self.bikes
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _note(last_success_at: datetime | None) -> str:
    if last_success_at is None:
        return "aucune donnée"
    return f"maj {last_success_at:%H:%M}"


def build_view(
    state: DashboardState,
    now: datetime,
    *,
    tcl_stale_after_seconds: float,
    velov_stale_after_seconds: float,
) -> DashboardView:
    tcl_stale = state.tcl.status_at(now, tcl_stale_after_seconds) in STALE_STATUSES
    velov_stale = state.velov.status_at(now, velov_stale_after_seconds) in STALE_STATUSES

    stops: list[StopBlock] = []
    for board in state.tcl.data or ():
        grouped: dict[tuple[str, str], list[str]] = {}
        for departure in board.departures:
            grouped.setdefault((departure.line, departure.direction), []).append(
                format_wait(departure.minutes_until(now))
            )
        stops.append(
            StopBlock(
                title=board.stop_name,
                lines=tuple(
                    DepartureLine(line=line, direction=direction, waits=tuple(waits))
                    for (line, direction), waits in grouped.items()
                ),
                stale=tcl_stale,
                note=_note(state.tcl.last_success_at) if tcl_stale else "",
            )
        )

    bikes = tuple(
        BikeBlock(
            label=station.label,
            bikes=station.bikes_available,
            docks=station.docks_available,
            capacity=station.capacity,
            stale=velov_stale,
            note=_note(state.velov.last_success_at) if velov_stale else "",
        )
        for station in state.velov.data or ()
    )

    return DashboardView(as_of=f"{now:%H:%M}", stops=tuple(stops), bikes=bikes)
