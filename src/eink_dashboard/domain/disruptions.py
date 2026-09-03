from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class TransitDisruption:
    source_id: str
    lines: tuple[str, ...]
    summary: str
    description: str
    valid_from: datetime | None
    valid_until: datetime | None
    severity: str | None
    planned: bool | None

    def is_active(self, now: datetime) -> bool:
        if self.valid_from is not None and now < self.valid_from:
            return False
        return not (self.valid_until is not None and now > self.valid_until)
