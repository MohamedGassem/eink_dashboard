"""Modèles permissifs du flux SIRI Situation Exchange de data.grandlyon.com.

Structure relevée sur une capture réelle (voir docs/tcl-sx-api-notes.md) :

    Siri.ServiceDelivery.SituationExchangeDelivery[].Situations.PtSituationElement[]

Chaque `PtSituationElement` porte `SituationNumber.value`, `ValidityPeriod[]`,
`Description[].value` et une arborescence `Consequences.Consequence[].Affects
.Networks.AffectedNetwork[].AffectedLine[].LineRef.value`. Tous les modèles
tolèrent les champs supplémentaires et les branches absentes.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

_CONFIG = ConfigDict(extra="ignore", populate_by_name=True)


class TextValue(BaseModel):
    model_config = _CONFIG

    value: str | None = None


class LineRef(BaseModel):
    model_config = _CONFIG

    value: str | None = Field(default=None)


class AffectedLine(BaseModel):
    model_config = _CONFIG

    line_ref: LineRef | None = Field(default=None, alias="LineRef")


class AffectedNetwork(BaseModel):
    model_config = _CONFIG

    affected_line: list[AffectedLine] = Field(default_factory=list, alias="AffectedLine")


class Networks(BaseModel):
    model_config = _CONFIG

    affected_network: list[AffectedNetwork] = Field(default_factory=list, alias="AffectedNetwork")


class Affects(BaseModel):
    model_config = _CONFIG

    networks: Networks | None = Field(default=None, alias="Networks")


class Consequence(BaseModel):
    model_config = _CONFIG

    affects: Affects | None = Field(default=None, alias="Affects")


class Consequences(BaseModel):
    model_config = _CONFIG

    consequence: list[Consequence] = Field(default_factory=list, alias="Consequence")


class ValidityPeriod(BaseModel):
    model_config = _CONFIG

    start_time: datetime | None = Field(default=None, alias="StartTime")
    end_time: datetime | None = Field(default=None, alias="EndTime")


class PtSituationElement(BaseModel):
    model_config = _CONFIG

    situation_number: TextValue | None = Field(default=None, alias="SituationNumber")
    validity_period: list[ValidityPeriod] = Field(default_factory=list, alias="ValidityPeriod")
    description: list[TextValue] = Field(default_factory=list, alias="Description")
    summary: list[TextValue] = Field(default_factory=list, alias="Summary")
    consequences: Consequences | None = Field(default=None, alias="Consequences")
    report_type: str | None = Field(default=None, alias="ReportType")
    miscellaneous_reason: str | None = Field(default=None, alias="MiscellaneousReason")
    planned: bool | None = Field(default=None, alias="Planned")


class Situations(BaseModel):
    model_config = _CONFIG

    pt_situation_element: list[PtSituationElement] = Field(
        default_factory=list, alias="PtSituationElement"
    )


class SituationExchangeDelivery(BaseModel):
    model_config = _CONFIG

    situations: Situations | None = Field(default=None, alias="Situations")


class ServiceDelivery(BaseModel):
    model_config = _CONFIG

    situation_exchange_delivery: list[SituationExchangeDelivery] = Field(
        default_factory=list, alias="SituationExchangeDelivery"
    )


class Siri(BaseModel):
    model_config = _CONFIG

    service_delivery: ServiceDelivery | None = Field(default=None, alias="ServiceDelivery")


class SiriDocument(BaseModel):
    model_config = _CONFIG

    siri: Siri | None = Field(default=None, alias="Siri")

    def situations(self) -> list[PtSituationElement]:
        if self.siri is None or self.siri.service_delivery is None:
            return []
        elements: list[PtSituationElement] = []
        for delivery in self.siri.service_delivery.situation_exchange_delivery:
            if delivery.situations is not None:
                elements.extend(delivery.situations.pt_situation_element)
        return elements
