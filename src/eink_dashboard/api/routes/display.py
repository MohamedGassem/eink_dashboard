"""Contrat panneau ↔ Home Assistant, découplé du protocole TRMNL.

- ``GET /api/v1/display/meta`` : hash de contenu + cadence conseillée.
- ``GET /image/dashboard.bmp`` : BMP 1 bit 800x480 sous URL stable, avec ``ETag``.

Le hash et le BMP proviennent du pipeline existant (``build_view`` →
``content_hash`` → ``render`` → ``to_bmp_bytes``) ; rien n'est recalculé ici.
"""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Header
from fastapi.responses import Response

from eink_dashboard.api.deps import ConfigDep, ImagesDep, SettingsDep, StoreDep, TzDep
from eink_dashboard.core.config import DashboardConfig, Settings
from eink_dashboard.render.images import ImageCache, to_bmp_bytes
from eink_dashboard.render.layout import render
from eink_dashboard.services.dashboard import refresh_rate_for, view_for
from eink_dashboard.state import Store

router = APIRouter()


def _hash_and_bmp(
    store: Store,
    config: DashboardConfig,
    settings: Settings,
    now: datetime,
    images: ImageCache,
) -> tuple[str, bytes]:
    view = view_for(store, config, settings, now)
    content_hash = view.content_hash()
    filename = f"dash-{content_hash}.bmp"
    payload = images.get(filename)
    if payload is None:
        payload = to_bmp_bytes(render(view))
        images.put(filename, payload)
    return content_hash, payload


@router.get("/api/v1/display/meta")
async def display_meta(
    store: StoreDep, config: ConfigDep, settings: SettingsDep, tz: TzDep
) -> dict[str, Any]:
    now = datetime.now(tz)
    view = view_for(store, config, settings, now)
    return {
        "content_hash": view.content_hash(),
        "refresh_seconds": refresh_rate_for(now),
    }


@router.get("/image/dashboard.bmp")
async def dashboard_bmp(
    store: StoreDep,
    config: ConfigDep,
    settings: SettingsDep,
    tz: TzDep,
    images: ImagesDep,
    if_none_match: Annotated[str | None, Header()] = None,
) -> Response:
    content_hash, payload = _hash_and_bmp(store, config, settings, datetime.now(tz), images)
    etag = f'"{content_hash}"'
    headers = {"ETag": etag, "Cache-Control": "no-cache"}
    if if_none_match is not None and if_none_match.strip() == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=payload, media_type="image/bmp", headers=headers)
