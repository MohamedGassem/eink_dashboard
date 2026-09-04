import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from eink_dashboard.core.config import DashboardConfig
from eink_dashboard.domain.disruptions import TransitDisruption
from eink_dashboard.state import DashboardState

MAX_WAIT_MINUTES = 60
MAX_NEXT_WAITS = 3
MAX_ALERTS = 2

# En journée (de 09:00 à 21:00 locale) le hash est « grossier » : les comptes à
# rebours, la météo et le nombre exact de vélos ne le modifient plus. Il ne bouge
# que sur évènement (perturbation active, station Vélo'v sous le seuil) ou au
# passage d'un quart d'heure (``quarter_hour_key``) — garantissant un redessin
# e-ink au moins tous les 15 min et un horodatage qui reste vivant.
DAY_COARSE_START_MINUTE = 9 * 60
DAY_COARSE_END_MINUTE = 21 * 60
# La nuit (21:00 à 07:30 locale) le panneau est totalement figé : le hash ne
# dépend plus que de ce créneau, donc plus aucun redessin e-ink — pas même sur
# perturbation. Bornes alignées sur ``refresh_rate_for`` (services/dashboard).
NIGHT_START_MINUTE = 21 * 60
NIGHT_END_MINUTE = 7 * 60 + 30
LOW_BIKES_THRESHOLD = 3
# Garde-fou caractères ; la largeur pixel réelle reste gérée par le layout.
ALERT_TEXT_LIMIT = 110
# status_at renvoie ok / degraded / stale / unavailable ; tout sauf ok vaut
# « donnée à ne pas présenter comme actuelle » côté affichage.
STALE_STATUSES = {"degraded", "stale", "unavailable"}

TRAFFIC_UNAVAILABLE = "Info trafic indisponible"
WEATHER_UNAVAILABLE = "Météo indisponible"


def in_coarse_window(now: datetime) -> bool:
    """Vrai entre 09:00 et 21:00 (heure locale du ``now`` fourni)."""
    minutes = now.hour * 60 + now.minute
    return DAY_COARSE_START_MINUTE <= minutes < DAY_COARSE_END_MINUTE


def in_night_window(now: datetime) -> bool:
    """Vrai de 21:00 à 07:30 (heure locale du ``now`` fourni)."""
    minutes = now.hour * 60 + now.minute
    return minutes >= NIGHT_START_MINUTE or minutes < NIGHT_END_MINUTE


def quarter_hour_key(now: datetime) -> str:
    """Identifiant du créneau de 15 min courant (``2026-09-04T10:15``). Sert de
    grain au hash « coarse » de journée : il change quatre fois par heure, donc
    le panneau se redessine au moins tous les quarts d'heure."""
    return f"{now:%Y-%m-%dT%H}:{now.minute // 15 * 15:02d}"


def format_wait(minutes: int) -> str:
    if minutes <= 0:
        return "à quai"
    if minutes > MAX_WAIT_MINUTES:
        return f"+{MAX_WAIT_MINUTES} min"
    return f"{minutes} min"


def format_bikes(count: int) -> str:
    return f"{count} vélo" if abs(count) <= 1 else f"{count} vélos"


@dataclass(frozen=True, slots=True)
class DepartureRow:
    line: str
    direction: str
    first_wait: str
    next_waits: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BikeRow:
    label: str
    bikes: int
    stale: bool


@dataclass(frozen=True, slots=True)
class AlertRow:
    line: str
    text: str


@dataclass(frozen=True, slots=True)
class WeatherRow:
    temperature: str
    condition: str


@dataclass(frozen=True, slots=True)
class DashboardView:
    as_of: str
    departures: tuple[DepartureRow, ...]
    bikes: tuple[BikeRow, ...]
    alerts: tuple[AlertRow, ...]
    weather: WeatherRow | None
    traffic_note: str
    # De 09:00 à 21:00 : hash « grossier », ne réagit qu'aux évènements et au
    # quart d'heure (cf. constantes).
    coarse: bool = False
    # De 21:00 à 07:30 : hash figé, ne réagit plus à rien (implique ``coarse``).
    night: bool = False
    # Créneau de 15 min courant ; n'entre dans le hash qu'en mode ``coarse`` non nuit.
    quarter: str = ""

    def _hash_payload(self) -> dict[str, object]:
        if self.night:
            return {"night": True}
        if self.coarse:
            return {
                "coarse": True,
                "quarter": self.quarter,
                "bikes_low": [row.stale or row.bikes < LOW_BIKES_THRESHOLD for row in self.bikes],
                "alerts": [[row.line, row.text] for row in self.alerts],
                "traffic_note": self.traffic_note,
            }
        return {
            "departures": [
                [row.line, row.direction, row.first_wait, list(row.next_waits)]
                for row in self.departures
            ],
            "bikes": [[row.label, row.bikes, row.stale] for row in self.bikes],
            "alerts": [[row.line, row.text] for row in self.alerts],
            "weather": (
                None if self.weather is None else [self.weather.temperature, self.weather.condition]
            ),
            "traffic_note": self.traffic_note,
        }

    def content_hash(self) -> str:
        payload = json.dumps(self._hash_payload(), ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _departures(
    state: DashboardState, now: datetime, config: DashboardConfig
) -> tuple[DepartureRow, ...]:
    # Un arrêt suivi = un sens : on regroupe par (arrêt, ligne), pas par direction.
    # Les terminus intermédiaires (Hauts de Feuilly, Essarts-Iris…) se fondent
    # ainsi dans la ligne de leur arrêt au lieu d'ajouter des lignes à l'écran.
    label_by_stop = {stop.name: stop.label for stop in config.tcl_stops if stop.label}
    grouped: dict[tuple[str, str], list[str]] = {}
    first_direction: dict[tuple[str, str], str] = {}
    order: list[tuple[str, str]] = []
    for board in state.tcl.data or ():
        for departure in board.departures:
            key = (board.stop_name, departure.line)
            if key not in grouped:
                grouped[key] = []
                first_direction[key] = departure.direction
                order.append(key)
            grouped[key].append(format_wait(departure.minutes_until(now)))

    rows: list[DepartureRow] = []
    for stop_name, line in order:
        key = (stop_name, line)
        waits = grouped[key]
        direction = label_by_stop.get(stop_name) or config.alias_for(first_direction[key])
        rows.append(
            DepartureRow(
                line=line,
                direction=direction,
                first_wait=waits[0],
                next_waits=tuple(waits[1 : 1 + MAX_NEXT_WAITS]),
            )
        )
    return tuple(rows)


def _bikes(state: DashboardState, *, stale: bool) -> tuple[BikeRow, ...]:
    return tuple(
        BikeRow(label=station.label, bikes=station.bikes_available, stale=stale)
        for station in state.velov.data or ()
    )


def _alerts(disruptions: tuple[TransitDisruption, ...], now: datetime) -> tuple[AlertRow, ...]:
    # Une alerte par jeu de lignes affectées ; on garde la plus ancienne (source_id)
    # pour une image stable. T2 et D sont à priorité équivalente.
    by_lines: dict[tuple[str, ...], TransitDisruption] = {}
    for disruption in disruptions:
        if not disruption.is_active(now):
            continue
        current = by_lines.get(disruption.lines)
        if current is None or disruption.source_id < current.source_id:
            by_lines[disruption.lines] = disruption

    ordered = sorted(by_lines.values(), key=lambda d: (d.lines, d.source_id))
    rows: list[AlertRow] = []
    for disruption in ordered[:MAX_ALERTS]:
        text = disruption.summary.strip()
        if len(text) > ALERT_TEXT_LIMIT:
            text = text[: ALERT_TEXT_LIMIT - 1].rstrip() + "…"
        rows.append(AlertRow(line="/".join(disruption.lines), text=text))
    return tuple(rows)


def _weather(state: DashboardState, *, enabled: bool, stale: bool) -> WeatherRow | None:
    if not enabled:
        return None
    snapshot = state.weather.data
    if stale or snapshot is None:
        return WeatherRow(temperature="", condition=WEATHER_UNAVAILABLE)
    condition = f"Pluie vers {snapshot.rain_at.hour}h" if snapshot.rain_at is not None else "Sec"
    return WeatherRow(temperature=f"{round(snapshot.temperature_c)}°C", condition=condition)


def build_view(
    state: DashboardState,
    now: datetime,
    config: DashboardConfig,
    *,
    tcl_stale_after_seconds: float,
    velov_stale_after_seconds: float,
    tcl_disruptions_stale_after_seconds: float,
    weather_stale_after_seconds: float,
    coarse_enabled: bool = True,
) -> DashboardView:
    velov_stale = state.velov.status_at(now, velov_stale_after_seconds) in STALE_STATUSES
    disruptions_enabled = config.disruptions is not None and bool(config.disruptions.lines)
    disruptions_stale = (
        state.tcl_disruptions.status_at(now, tcl_disruptions_stale_after_seconds) in STALE_STATUSES
    )
    weather_enabled = config.weather is not None
    weather_stale = state.weather.status_at(now, weather_stale_after_seconds) in STALE_STATUSES

    if not disruptions_enabled:
        alerts: tuple[AlertRow, ...] = ()
        traffic_note = ""
    elif disruptions_stale:
        alerts = ()
        traffic_note = TRAFFIC_UNAVAILABLE
    else:
        alerts = _alerts(state.tcl_disruptions.data or (), now)
        traffic_note = ""

    night = coarse_enabled and in_night_window(now)
    return DashboardView(
        as_of=f"{now:%H:%M}",
        departures=_departures(state, now, config),
        bikes=_bikes(state, stale=velov_stale),
        alerts=alerts,
        weather=_weather(state, enabled=weather_enabled, stale=weather_stale),
        traffic_note=traffic_note,
        coarse=night or (coarse_enabled and in_coarse_window(now)),
        night=night,
        quarter=quarter_hour_key(now),
    )
