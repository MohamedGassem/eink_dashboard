from datetime import datetime
from typing import Any

from fastapi import APIRouter

from eink_dashboard.api.deps import SettingsDep, StoreDep, TzDep
from eink_dashboard.services.dashboard import STALE_INTERVAL_FACTOR, dashboard_payload

router = APIRouter()


@router.get("/api/v1/dashboard")
async def dashboard(store: StoreDep, settings: SettingsDep, tz: TzDep) -> dict[str, Any]:
    now = datetime.now(tz)
    return dashboard_payload(
        store.state,
        now,
        tcl_stale_after_seconds=settings.tcl_refresh_seconds * STALE_INTERVAL_FACTOR,
        velov_stale_after_seconds=settings.velov_refresh_seconds * STALE_INTERVAL_FACTOR,
    )
