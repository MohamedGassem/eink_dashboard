from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any

from eink_dashboard.core.config import DashboardConfig, Settings
from eink_dashboard.render.viewmodel import LOW_BIKES_THRESHOLD, DashboardView, build_view
from eink_dashboard.state import DashboardState, ProviderResult, Store

# La spec §8 bascule un fournisseur en ``stale`` au-delà de trois fois son
# intervalle de rafraîchissement. Chaque fournisseur porte le sien.
STALE_INTERVAL_FACTOR = 3


def view_for(
    store: Store,
    config: DashboardConfig,
    settings: Settings,
    now: datetime,
    *,
    coarse_enabled: bool = True,
) -> DashboardView:
    return build_view(
        store.state,
        now,
        config,
        tcl_stale_after_seconds=settings.tcl_refresh_seconds * STALE_INTERVAL_FACTOR,
        velov_stale_after_seconds=settings.velov_refresh_seconds * STALE_INTERVAL_FACTOR,
        tcl_disruptions_stale_after_seconds=(
            settings.tcl_disruptions_refresh_seconds * STALE_INTERVAL_FACTOR
        ),
        weather_stale_after_seconds=settings.weather_refresh_seconds * STALE_INTERVAL_FACTOR,
        coarse_enabled=coarse_enabled,
    )


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


# Cadence de réveil du panneau (secondes), pensée pour le mode batterie / deep sleep.
#   07:30 à 09:00 : décision du trajet, on rafraîchit souvent.
#   09:00 à 21:00 : réveil au moins tous les quarts d'heure (aligné sur le grain du
#                   hash « coarse ») ; on raccourcit encore si un évènement est en cours.
#   21:00 à 07:30 : on dort jusqu'au matin (plafonné : OTA, dérive d'horloge).
PEAK_REFRESH = 180
DAY_EVENT_REFRESH = 300
DAY_IDLE_REFRESH = 15 * 60
NIGHT_MAX_SLEEP = 4 * 3600

_MORNING_START = 7 * 60 + 30
_PEAK_END = 9 * 60
_NIGHT_START = 21 * 60


def view_has_event(view: DashboardView) -> bool:
    """Un évènement (perturbation active ou station Vélo'v basse) justifie de
    raccourcir la cadence et de rafraîchir le panneau en pleine journée."""
    if view.alerts or view.traffic_note:
        return True
    return any(row.stale or row.bikes < LOW_BIKES_THRESHOLD for row in view.bikes)


def _seconds_until(now: datetime, hour: int, minute: int) -> int:
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return int((target - now).total_seconds())


def refresh_rate_for(now: datetime, *, has_event: bool = False) -> int:
    minutes = now.hour * 60 + now.minute
    if minutes >= _NIGHT_START or minutes < _MORNING_START:
        return min(_seconds_until(now, 7, 30), NIGHT_MAX_SLEEP)
    if minutes < _PEAK_END:
        return PEAK_REFRESH
    return DAY_EVENT_REFRESH if has_event else DAY_IDLE_REFRESH
