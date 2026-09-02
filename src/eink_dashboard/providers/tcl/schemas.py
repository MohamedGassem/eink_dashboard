from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator

PARIS = ZoneInfo("Europe/Paris")

# Table de correspondance nom interne -> champ de l'API datapusher.
# Remplie à partir de docs/tcl-api-notes.md (capture réelle du 2026-09-02).
# Deux garde-fous dans tests/unit/test_tcl_mapper.py :
#   - test_fixture_contains_every_mapped_field : les champs existent dans l'API.
#   - test_tcl_fields_matches_schema_aliases : la table colle aux alias ci-dessous.
TCL_FIELDS: dict[str, str] = {
    "stop_id": "id",
    "line": "ligne",
    "direction": "direction",
    "expected_at": "heurepassage",
    "kind": "type",
}


class PassageRecord(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True, coerce_numbers_to_str=True)

    stop_id: str = Field(alias="id")
    line: str = Field(alias="ligne")
    direction: str = Field(alias="direction")
    expected_at: datetime = Field(alias="heurepassage")
    kind: str = Field(alias="type")

    @field_validator("expected_at", mode="after")
    @classmethod
    def _assume_paris(cls, value: datetime) -> datetime:
        # `heurepassage` est un datetime naïf en heure locale de Lyon.
        return value if value.tzinfo is not None else value.replace(tzinfo=PARIS)


class PassageFeed(BaseModel):
    model_config = ConfigDict(extra="ignore")

    nb_results: int = 0
    values: list[PassageRecord] = Field(default_factory=list)
