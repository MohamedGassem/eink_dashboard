from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from eink_dashboard.domain.bikes import BikeStation
from eink_dashboard.domain.disruptions import TransitDisruption
from eink_dashboard.domain.transit import StopBoard
from eink_dashboard.domain.weather import WeatherSnapshot

ProviderStatus = Literal["ok", "degraded", "stale", "unavailable"]


@dataclass(slots=True)
class ProviderResult[T]:
    name: str
    data: T | None = None
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    source_updated_at: datetime | None = None
    last_error: str | None = None

    def age_seconds(self, now: datetime) -> float | None:
        freshness_at = self.source_updated_at or self.last_success_at
        if freshness_at is None:
            return None
        return (now - freshness_at).total_seconds()

    def status_at(self, now: datetime, stale_after_seconds: float) -> ProviderStatus:
        if stale_after_seconds <= 0:
            raise ValueError("le seuil de fraîcheur doit être strictement positif")
        if self.data is None or self.last_success_at is None:
            return "unavailable"
        age = self.age_seconds(now)
        if age is not None and age > stale_after_seconds:
            return "stale"
        if self.last_error is not None:
            return "degraded"
        return "ok"


@dataclass(slots=True)
class DashboardState:
    tcl: ProviderResult[tuple[StopBoard, ...]] = field(
        default_factory=lambda: ProviderResult[tuple[StopBoard, ...]](name="tcl")
    )
    velov: ProviderResult[tuple[BikeStation, ...]] = field(
        default_factory=lambda: ProviderResult[tuple[BikeStation, ...]](name="velov")
    )
    tcl_disruptions: ProviderResult[tuple[TransitDisruption, ...]] = field(
        default_factory=lambda: ProviderResult[tuple[TransitDisruption, ...]](
            name="tcl_disruptions"
        )
    )
    weather: ProviderResult[WeatherSnapshot] = field(
        default_factory=lambda: ProviderResult[WeatherSnapshot](name="weather")
    )


class Store:
    def __init__(self) -> None:
        self._state = DashboardState()

    @property
    def state(self) -> DashboardState:
        return self._state

    def _slot(self, name: str) -> ProviderResult[Any]:
        slot = getattr(self._state, name, None)
        if slot is None:
            raise KeyError(f"fournisseur inconnu: {name}")
        return slot  # type: ignore[no-any-return]

    def record_success(
        self,
        name: str,
        data: object,
        now: datetime,
        *,
        source_updated_at: datetime | None = None,
    ) -> None:
        slot = self._slot(name)
        slot.data = data
        slot.last_attempt_at = now
        slot.last_success_at = now
        slot.source_updated_at = source_updated_at
        slot.last_error = None

    def record_failure(self, name: str, error: str, now: datetime) -> None:
        slot = self._slot(name)
        slot.last_attempt_at = now
        slot.last_error = error
