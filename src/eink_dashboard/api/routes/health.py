from datetime import datetime
from typing import Any

from fastapi import APIRouter

from eink_dashboard.api.deps import SettingsDep, StoreDep, TzDep
from eink_dashboard.services.dashboard import STALE_INTERVAL_FACTOR, provider_health

router = APIRouter()


@router.get("/health")
async def health(store: StoreDep, settings: SettingsDep, tz: TzDep) -> dict[str, Any]:
    now = datetime.now(tz)
    return {
        "status": "ok",
        "providers": {
            "tcl": provider_health(
                store.state.tcl, now, settings.tcl_refresh_seconds * STALE_INTERVAL_FACTOR
            ),
            "velov": provider_health(
                store.state.velov, now, settings.velov_refresh_seconds * STALE_INTERVAL_FACTOR
            ),
            "tcl_disruptions": provider_health(
                store.state.tcl_disruptions,
                now,
                settings.tcl_disruptions_refresh_seconds * STALE_INTERVAL_FACTOR,
            ),
            "weather": provider_health(
                store.state.weather,
                now,
                settings.weather_refresh_seconds * STALE_INTERVAL_FACTOR,
            ),
        },
    }


@router.get("/health/live")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}
