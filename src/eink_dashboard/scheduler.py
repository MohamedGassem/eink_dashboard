import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

import structlog

from eink_dashboard.providers.base import Provider, ProviderSnapshot
from eink_dashboard.state import Store

log = structlog.get_logger()


async def _fetch_with_one_retry(provider: Provider[Any]) -> ProviderSnapshot[Any]:
    try:
        return await provider.fetch()
    except Exception as first_error:
        log.info("provider.retry", provider=provider.name, error=str(first_error))
        return await provider.fetch()


async def run_provider_loop(
    provider: Provider[Any],
    store: Store,
    clock: Callable[[], datetime],
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    stop_after: int | None = None,
) -> None:
    """Refresh one provider forever, one tick per ``provider.interval`` seconds.

    A failed tick is retried once immediately, then abandoned until the next
    tick. The last good data is kept; read-time ``ProviderResult.status_at``
    decides whether it counts as ``degraded`` or ``stale``.
    """
    iterations = 0
    while stop_after is None or iterations < stop_after:
        iterations += 1
        try:
            snapshot = await _fetch_with_one_retry(provider)
        except Exception as error:
            store.record_failure(provider.name, str(error), clock())
            log.warning("provider.failed", provider=provider.name, error=str(error))
        else:
            store.record_success(
                provider.name,
                snapshot.data,
                clock(),
                source_updated_at=snapshot.source_updated_at,
            )
            log.info("provider.refreshed", provider=provider.name)

        await sleep(provider.interval)
