from eink_dashboard.core.config import TclStop
from eink_dashboard.domain.transit import Departure, StopBoard
from eink_dashboard.providers.tcl.schemas import PassageFeed, PassageRecord

# "E" = estimé (temps réel), "T" = théorique. Voir docs/tcl-api-notes.md.
REALTIME_KIND = "E"


def _matches(record: PassageRecord, stop: TclStop) -> bool:
    if stop.lines and record.line not in stop.lines:
        return False
    if stop.directions:
        haystack = record.direction.casefold()
        return any(wanted.casefold() in haystack for wanted in stop.directions)
    return True


def to_stop_boards(feed: PassageFeed, stop: TclStop, limit: int = 4) -> StopBoard:
    departures = [
        Departure(
            line=record.line,
            direction=record.direction,
            expected_at=record.expected_at,
            is_realtime=record.kind == REALTIME_KIND,
        )
        for record in feed.values
        if _matches(record, stop)
    ]
    departures.sort(key=lambda departure: departure.expected_at)
    return StopBoard(stop_name=stop.name, departures=tuple(departures[:limit]), available=True)
