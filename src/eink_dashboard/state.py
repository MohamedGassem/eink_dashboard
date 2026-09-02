from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from eink_dashboard.domain.bikes import BikeStation
from eink_dashboard.domain.transit import StopBoard

ProviderStatus = Literal["ok", "stale", "error", "unknown"]


@dataclass(slots=True)
class ProviderResult[T]:
    name: str
    status: ProviderStatus = "unknown"
    data: T | None = None
    updated_at: datetime | None = None
    error: str | None = None

    def age_seconds(self, now: datetime) -> float | None:
        if self.updated_at is None:
            return None
        return (now - self.updated_at).total_seconds()


@dataclass(slots=True)
class DashboardState:
    tcl: ProviderResult[tuple[StopBoard, ...]] = field(
        default_factory=lambda: ProviderResult[tuple[StopBoard, ...]](name="tcl")
    )
    velov: ProviderResult[tuple[BikeStation, ...]] = field(
        default_factory=lambda: ProviderResult[tuple[BikeStation, ...]](name="velov")
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

    def record_success(self, name: str, data: object, now: datetime) -> None:
        slot = self._slot(name)
        slot.data = data
        slot.status = "ok"
        slot.updated_at = now
        slot.error = None

    def record_failure(self, name: str, error: str, now: datetime) -> None:
        slot = self._slot(name)
        slot.status = "error"
        slot.error = error

    def mark_stale_if_old(self, now: datetime, max_age_seconds: float) -> None:
        for name in ("tcl", "velov"):
            slot = self._slot(name)
            age = slot.age_seconds(now)
            if slot.status == "ok" and age is not None and age > max_age_seconds:
                slot.status = "stale"
