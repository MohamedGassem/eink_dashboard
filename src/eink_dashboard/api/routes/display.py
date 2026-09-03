"""Contrat panneau ↔ Home Assistant, découplé du protocole TRMNL.

- ``GET /api/v1/display/meta``  : hash de contenu + cadence conseillée.
- ``GET /image/dashboard.bmp``  : BMP 1 bit 800x480 sous URL stable, avec ``ETag``.
- ``GET /image/dashboard.png``  : même image en PNG 1 bit (fallback ``online_image``).

Le hash et l'image proviennent du pipeline existant (``build_view`` →
``content_hash`` → ``render`` → ``to_bmp_bytes`` / ``to_png_bytes``) ; rien n'est
recalculé ici.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Header
from fastapi.responses import Response
from PIL import Image

from eink_dashboard.api.deps import ConfigDep, ImagesDep, SettingsDep, StoreDep, TzDep
from eink_dashboard.core.config import DashboardConfig, Settings
from eink_dashboard.render.images import ImageCache, to_bmp_bytes, to_png_bytes
from eink_dashboard.render.layout import render
from eink_dashboard.services.dashboard import refresh_rate_for, view_for
from eink_dashboard.state import Store

router = APIRouter()


def _cached_image(
    store: Store,
    config: DashboardConfig,
    settings: Settings,
    now: datetime,
    images: ImageCache,
    *,
    suffix: str,
    encode: Callable[[Image.Image], bytes],
) -> tuple[str, bytes]:
    view = view_for(store, config, settings, now)
    content_hash = view.content_hash()
    key = f"dash-{content_hash}.{suffix}"
    payload = images.get(key)
    if payload is None:
        payload = encode(render(view))
        images.put(key, payload)
    return content_hash, payload


def _image_response(
    content_hash: str, payload: bytes, media_type: str, if_none_match: str | None
) -> Response:
    etag = f'"{content_hash}"'
    headers = {"ETag": etag, "Cache-Control": "no-cache"}
    if if_none_match is not None and if_none_match.strip() == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=payload, media_type=media_type, headers=headers)


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
    content_hash, payload = _cached_image(
        store, config, settings, datetime.now(tz), images, suffix="bmp", encode=to_bmp_bytes
    )
    return _image_response(content_hash, payload, "image/bmp", if_none_match)


@router.get("/image/dashboard.png")
async def dashboard_png(
    store: StoreDep,
    config: ConfigDep,
    settings: SettingsDep,
    tz: TzDep,
    images: ImagesDep,
    if_none_match: Annotated[str | None, Header()] = None,
) -> Response:
    content_hash, payload = _cached_image(
        store, config, settings, datetime.now(tz), images, suffix="png", encode=to_png_bytes
    )
    return _image_response(content_hash, payload, "image/png", if_none_match)
