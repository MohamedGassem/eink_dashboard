from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class ProviderError(RuntimeError):
    """Expected operational failure while acquiring provider data."""


@dataclass(frozen=True, slots=True)
class ProviderSnapshot[T]:
    data: T
    source_updated_at: datetime | None = None


class Provider[T](Protocol):
    name: str
    interval: float

    async def fetch(self) -> ProviderSnapshot[T]: ...
