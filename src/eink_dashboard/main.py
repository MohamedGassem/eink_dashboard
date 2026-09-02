import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI

from eink_dashboard.api.routes import dashboard as dashboard_routes
from eink_dashboard.api.routes import health
from eink_dashboard.core.config import (
    get_settings,
    load_dashboard_config,
    validate_runtime_requirements,
)
from eink_dashboard.core.logging import configure_logging
from eink_dashboard.providers.base import Provider
from eink_dashboard.providers.tcl.client import TclClient
from eink_dashboard.providers.velov.client import VelovClient
from eink_dashboard.scheduler import run_provider_loop
from eink_dashboard.state import Store

TIMEOUT = httpx.Timeout(10.0, connect=5.0)

# L'API appareil (Task 12) n'est pas encore câblée : ses identifiants ne sont
# pas exigés au démarrage.
DEVICE_API_ENABLED = False


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    config = load_dashboard_config(settings.config_path)
    validate_runtime_requirements(settings, config, device_enabled=DEVICE_API_ENABLED)
    tz = ZoneInfo(settings.tz)

    store = Store()
    http = httpx.AsyncClient(timeout=TIMEOUT)
    app.state.settings = settings
    app.state.store = store
    app.state.tz = tz

    providers: list[Provider[Any]] = []
    if config.velov_stations:
        providers.append(
            VelovClient(http, config.velov_stations, interval=settings.velov_refresh_seconds)
        )
    if config.tcl_stops:
        providers.append(
            TclClient(
                http,
                config.tcl_stops,
                settings.grandlyon_username,
                settings.grandlyon_password,
                interval=settings.tcl_refresh_seconds,
            )
        )

    tasks = [
        asyncio.create_task(run_provider_loop(provider, store, lambda: datetime.now(tz)))
        for provider in providers
    ]

    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await http.aclose()


configure_logging()

app = FastAPI(title="eink-dashboard", lifespan=lifespan)
app.include_router(health.router)
app.include_router(dashboard_routes.router)
