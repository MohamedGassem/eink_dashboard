from datetime import UTC, datetime, timedelta

from eink_dashboard.providers.base import ProviderError, ProviderSnapshot
from eink_dashboard.scheduler import run_provider_loop
from eink_dashboard.state import Store

T0 = datetime(2026, 9, 2, 8, 0, tzinfo=UTC)


class FakeClock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


async def no_sleep(_seconds: float) -> None:
    return None


class FlakyProvider:
    name = "velov"
    interval = 60.0

    def __init__(self, outcomes: list[object]) -> None:
        self._outcomes = outcomes
        self.calls = 0

    async def fetch(self) -> ProviderSnapshot[object]:
        outcome = self._outcomes[self.calls]
        self.calls += 1
        if isinstance(outcome, Exception):
            raise outcome
        return ProviderSnapshot(data=outcome)


def snapshot(payload: object) -> ProviderSnapshot[object]:
    return ProviderSnapshot(data=payload)


async def test_loop_records_success_and_unpacks_the_snapshot() -> None:
    store = Store()
    provider = FlakyProvider(["données"])

    await run_provider_loop(provider, store, FakeClock(), no_sleep, stop_after=1)

    assert store.state.velov.status_at(T0, stale_after_seconds=180) == "ok"
    assert store.state.velov.data == "données"
    assert store.state.velov.last_success_at == T0


async def test_loop_propagates_source_updated_at() -> None:
    store = Store()
    source_time = T0 - timedelta(minutes=5)

    class Provider:
        name = "velov"
        interval = 60.0

        async def fetch(self) -> ProviderSnapshot[object]:
            return ProviderSnapshot(data="données", source_updated_at=source_time)

    await run_provider_loop(Provider(), store, FakeClock(), no_sleep, stop_after=1)

    assert store.state.velov.source_updated_at == source_time


async def test_loop_retries_once_within_the_same_iteration() -> None:
    store = Store()
    provider = FlakyProvider([ProviderError("boum"), "données"])

    await run_provider_loop(provider, store, FakeClock(), no_sleep, stop_after=1)

    assert provider.calls == 2
    assert store.state.velov.status_at(T0, stale_after_seconds=180) == "ok"


async def test_loop_records_failure_and_keeps_running() -> None:
    store = Store()
    provider = FlakyProvider([ProviderError("boum"), ProviderError("boum"), "données"])

    await run_provider_loop(provider, store, FakeClock(), no_sleep, stop_after=2)

    assert provider.calls == 3
    assert store.state.velov.status_at(T0, stale_after_seconds=180) == "ok"


async def test_loop_keeps_last_good_data_after_a_failure() -> None:
    store = Store()
    provider = FlakyProvider(["données", ProviderError("boum"), ProviderError("boum")])
    clock = FakeClock()

    await run_provider_loop(provider, store, clock, no_sleep, stop_after=2)

    assert store.state.velov.data == "données"
    assert store.state.velov.last_error == "boum"
    assert store.state.velov.status_at(T0, stale_after_seconds=180) == "degraded"


async def test_loop_sleeps_for_the_provider_interval_between_ticks() -> None:
    store = Store()
    provider = FlakyProvider(["a", "b"])
    slept: list[float] = []

    async def record_sleep(seconds: float) -> None:
        slept.append(seconds)

    await run_provider_loop(provider, store, FakeClock(), record_sleep, stop_after=2)

    assert slept == [60.0, 60.0]
