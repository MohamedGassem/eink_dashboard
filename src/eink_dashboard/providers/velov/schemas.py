from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class VehicleTypeCount(BaseModel):
    model_config = ConfigDict(extra="ignore")

    vehicle_type_id: str
    count: int


class StationStatus(BaseModel):
    model_config = ConfigDict(extra="ignore")

    station_id: str
    num_vehicles_available: int
    num_docks_available: int
    vehicle_types_available: list[VehicleTypeCount]
    is_installed: bool
    is_renting: bool
    is_returning: bool
    last_reported: AwareDatetime


class StationStatusData(BaseModel):
    model_config = ConfigDict(extra="ignore")

    stations: list[StationStatus]


class StationStatusFeed(BaseModel):
    model_config = ConfigDict(extra="ignore")

    last_updated: AwareDatetime
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
    capacity: int | None = None


class StationInformationData(BaseModel):
    model_config = ConfigDict(extra="ignore")

    stations: list[StationInformation]


class StationInformationFeed(BaseModel):
    model_config = ConfigDict(extra="ignore")

    last_updated: AwareDatetime
    data: StationInformationData
