from typing import Protocol


class Provider[T](Protocol):
    name: str
    interval: float

    async def fetch(self) -> T: ...
