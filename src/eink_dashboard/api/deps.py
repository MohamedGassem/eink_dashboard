from datetime import tzinfo
from typing import Annotated

from fastapi import Depends, Request

from eink_dashboard.core.config import DashboardConfig, Settings
from eink_dashboard.render.images import ImageCache
from eink_dashboard.state import Store


def get_store(request: Request) -> Store:
    store: Store = request.app.state.store
    return store


def get_config(request: Request) -> DashboardConfig:
    config: DashboardConfig = request.app.state.config
    return config


def get_images(request: Request) -> ImageCache:
    images: ImageCache = request.app.state.images
    return images


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_tz(request: Request) -> tzinfo:
    tz: tzinfo = request.app.state.tz
    return tz


StoreDep = Annotated[Store, Depends(get_store)]
ConfigDep = Annotated[DashboardConfig, Depends(get_config)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
TzDep = Annotated[tzinfo, Depends(get_tz)]
ImagesDep = Annotated[ImageCache, Depends(get_images)]
