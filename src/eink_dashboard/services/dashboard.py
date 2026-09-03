from dataclasses import asdict
from datetime import datetime
from typing import Any

from eink_dashboard.state import DashboardState, ProviderResult

# La spec §8 bascule un fournisseur en ``stale`` au-delà de trois fois son
# intervalle de rafraîchissement. Chaque fournisseur porte le sien.
STALE_INTERVAL_FACTOR = 3


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def provider_health(
    result: ProviderResult[Any], now: datetime, stale_after_seconds: float
) -> dict[str, Any]:
    return {
        "status": result.status_at(now, stale_after_seconds),
        "age_seconds": result.age_seconds(now),
        "last_success_at": _iso(result.last_success_at),
        "source_updated_at": _iso(result.source_updated_at),
        "last_attempt_at": _iso(result.last_attempt_at),
        "last_error": result.last_error,
    }


def dashboard_payload(
    state: DashboardState,
    now: datetime,
    *,
    tcl_stale_after_seconds: float,
    velov_stale_after_seconds: float,
    tcl_disruptions_stale_after_seconds: float,
    weather_stale_after_seconds: float,
) -> dict[str, Any]:
    boards = state.tcl.data or ()
    stations = state.velov.data or ()
    disruptions = state.tcl_disruptions.data or ()
    weather = state.weather.data
    return {
        "tcl": {
            **provider_health(state.tcl, now, tcl_stale_after_seconds),
            "stops": [
                {
                    "stop_name": board.stop_name,
                    "available": board.available,
                    "departures": [
                        {
                            "line": departure.line,
                            "direction": departure.direction,
                            "expected_at": departure.expected_at.isoformat(),
                            "minutes": departure.minutes_until(now),
                            "is_realtime": departure.is_realtime,
                        }
                        for departure in board.departures
                    ],
                }
                for board in boards
            ],
        },
        "velov": {
            **provider_health(state.velov, now, velov_stale_after_seconds),
            "stations": [
                {**asdict(station), "reported_at": station.reported_at.isoformat()}
                for station in stations
            ],
        },
        "tcl_disruptions": {
            **provider_health(state.tcl_disruptions, now, tcl_disruptions_stale_after_seconds),
            "disruptions": [
                {
                    "source_id": disruption.source_id,
                    "lines": list(disruption.lines),
                    "summary": disruption.summary,
                    "description": disruption.description,
                    "valid_from": _iso(disruption.valid_from),
                    "valid_until": _iso(disruption.valid_until),
                    "severity": disruption.severity,
                    "planned": disruption.planned,
                }
                for disruption in disruptions
            ],
        },
        "weather": {
            **provider_health(state.weather, now, weather_stale_after_seconds),
            "snapshot": (
                None
                if weather is None
                else {
                    "temperature_c": weather.temperature_c,
                    "rain_at": _iso(weather.rain_at),
                    "reported_at": weather.reported_at.isoformat(),
                }
            ),
        },
    }


# Cadence de réveil du panneau : court en pointe TCL, moyen en journée, long la nuit.
PEAK_REFRESH = 120
DAY_REFRESH = 300
NIGHT_REFRESH = 3600

_MORNING_PEAK = (7 * 60, 9 * 60 + 30)
_EVENING_PEAK = (17 * 60, 19 * 60 + 30)
_NIGHT_START = 23 * 60
_NIGHT_END = 6 * 60


def refresh_rate_for(now: datetime) -> int:
    minutes = now.hour * 60 + now.minute
    if minutes >= _NIGHT_START or minutes < _NIGHT_END:
        return NIGHT_REFRESH
    for start, end in (_MORNING_PEAK, _EVENING_PEAK):
        if start <= minutes < end:
            return PEAK_REFRESH
    return DAY_REFRESH
