from datetime import datetime
from typing import Any

from fastapi import APIRouter
from fastapi.responses import Response

from eink_dashboard.api.deps import ConfigDep, SettingsDep, StoreDep, TzDep
from eink_dashboard.render.images import to_png_bytes
from eink_dashboard.render.layout import render
from eink_dashboard.services.dashboard import (
    STALE_INTERVAL_FACTOR,
    dashboard_payload,
    view_for,
)

router = APIRouter()


@router.get("/api/v1/dashboard")
async def dashboard(store: StoreDep, settings: SettingsDep, tz: TzDep) -> dict[str, Any]:
    now = datetime.now(tz)
    return dashboard_payload(
        store.state,
        now,
        tcl_stale_after_seconds=settings.tcl_refresh_seconds * STALE_INTERVAL_FACTOR,
        velov_stale_after_seconds=settings.velov_refresh_seconds * STALE_INTERVAL_FACTOR,
        tcl_disruptions_stale_after_seconds=(
            settings.tcl_disruptions_refresh_seconds * STALE_INTERVAL_FACTOR
        ),
        weather_stale_after_seconds=settings.weather_refresh_seconds * STALE_INTERVAL_FACTOR,
    )


@router.get("/preview.png")
async def preview(store: StoreDep, config: ConfigDep, settings: SettingsDep, tz: TzDep) -> Response:
    view = view_for(store, config, settings, datetime.now(tz))
    return Response(content=to_png_bytes(render(view)), media_type="image/png")
