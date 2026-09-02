from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class VehicleTypeCount(BaseModel):
    model_config = ConfigDict(extra="ignore")

    vehicle_type_id: str
    count: int = 0


class StationStatus(BaseModel):
    model_config = ConfigDict(extra="ignore")

    station_id: str
    num_vehicles_available: int = 0
    num_docks_available: int = 0
    vehicle_types_available: list[VehicleTypeCount] = Field(default_factory=list)
    is_installed: bool = False
    is_renting: bool = False
    is_returning: bool = False
    last_reported: datetime


class StationStatusData(BaseModel):
    model_config = ConfigDict(extra="ignore")

    stations: list[StationStatus] = Field(default_factory=list)


class StationStatusFeed(BaseModel):
    model_config = ConfigDict(extra="ignore")

    last_updated: datetime
    data: StationStatusData


class LocalizedName(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str
    language: str = "fr"


class StationInformation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    station_id: str
    name: list[LocalizedName] = Field(default_factory=list)
    address: str | None = None
    capacity: int = 0


class StationInformationData(BaseModel):
    model_config = ConfigDict(extra="ignore")

    stations: list[StationInformation] = Field(default_factory=list)


class StationInformationFeed(BaseModel):
    model_config = ConfigDict(extra="ignore")

    last_updated: datetime
    data: StationInformationData
