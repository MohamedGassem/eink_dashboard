from datetime import datetime
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Body, Header, HTTPException, Response

from eink_dashboard.api.deps import ImagesDep, SettingsDep, StoreDep, TzDep
from eink_dashboard.render.images import ImageCache, to_bmp_bytes
from eink_dashboard.render.layout import render
from eink_dashboard.render.viewmodel import build_view
from eink_dashboard.services.dashboard import STALE_INTERVAL_FACTOR, refresh_rate_for

router = APIRouter()
log = structlog.get_logger()

FRIENDLY_ID = "LYON01"


def _check_mac(sent: str, expected: str) -> None:
    if not expected or sent.strip().casefold() != expected.strip().casefold():
        raise HTTPException(status_code=404, detail="appareil inconnu")


def _check_token(sent: str, expected: str) -> None:
    if not expected or sent != expected:
        raise HTTPException(status_code=401, detail="jeton invalide")


def _current_image(store: StoreDep, settings: SettingsDep, tz: TzDep, images: ImageCache) -> str:
    now = datetime.now(tz)
    view = build_view(
        store.state,
        now,
        tcl_stale_after_seconds=settings.tcl_refresh_seconds * STALE_INTERVAL_FACTOR,
        velov_stale_after_seconds=settings.velov_refresh_seconds * STALE_INTERVAL_FACTOR,
    )
    filename = f"dash-{view.content_hash()}.bmp"
    if images.get(filename) is None:
        images.put(filename, to_bmp_bytes(render(view)))
    return filename


def _image_url(settings: SettingsDep, filename: str) -> str:
    return f"{settings.public_base_url.rstrip('/')}/image/{filename}"


@router.get("/api/setup")
async def setup(
    store: StoreDep,
    settings: SettingsDep,
    tz: TzDep,
    images: ImagesDep,
    id: Annotated[str, Header()],
) -> dict[str, Any]:
    _check_mac(id, settings.device_mac)
    filename = _current_image(store, settings, tz, images)
    log.info("device.setup", mac=id)
    return {
        "status": 200,
        "api_key": settings.device_api_key,
        "friendly_id": FRIENDLY_ID,
        "image_url": _image_url(settings, filename),
        "filename": filename,
    }


@router.get("/api/display")
async def display(
    store: StoreDep,
    settings: SettingsDep,
    tz: TzDep,
    images: ImagesDep,
    id: Annotated[str, Header()],
    access_token: Annotated[str, Header()] = "",
    battery_voltage: Annotated[str | None, Header()] = None,
    fw_version: Annotated[str | None, Header()] = None,
    rssi: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    _check_mac(id, settings.device_mac)
    _check_token(access_token, settings.device_api_key)
    filename = _current_image(store, settings, tz, images)
    log.info("device.display", mac=id, battery=battery_voltage, rssi=rssi, fw=fw_version)
    return {
        "status": 0,
        "image_url": _image_url(settings, filename),
        "filename": filename,
        "refresh_rate": refresh_rate_for(datetime.now(tz)),
        "update_firmware": False,
        "firmware_url": None,
        "reset_firmware": False,
    }


@router.post("/api/log", status_code=204)
async def device_log(
    id: Annotated[str, Header()],
    payload: Annotated[dict[str, Any], Body()],
) -> Response:
    log.warning("device.log", mac=id, payload=payload)
    return Response(status_code=204)


@router.get("/image/{name}")
async def image(name: str, images: ImagesDep) -> Response:
    payload = images.get(name)
    if payload is None:
        raise HTTPException(status_code=404, detail="image inconnue")
    return Response(content=payload, media_type="image/bmp")
