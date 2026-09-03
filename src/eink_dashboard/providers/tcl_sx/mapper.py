"""Normalisation SIRI-SX brut -> `TransitDisruption` du domaine.

Rien hors de ce module ne connaît la structure SIRI. Le mapper ne garde que les
lignes explicitement suivies (via `DisruptionsConfig.line_refs`), jamais par
recherche de sous-chaîne dans un texte libre.
"""

import html
import re
from datetime import datetime, timedelta

from eink_dashboard.core.config import DisruptionsConfig
from eink_dashboard.domain.disruptions import TransitDisruption
from eink_dashboard.providers.tcl_sx.schemas import PtSituationElement, SiriDocument, TextValue

FALLBACK_TEXT = "Perturbation signalée"
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _clean(raw: str) -> str:
    without_tags = _TAG_RE.sub(" ", raw)
    return _WS_RE.sub(" ", html.unescape(without_tags)).strip()


def _first_text(entries: list[TextValue]) -> str | None:
    for entry in entries:
        if entry.value is None:
            continue
        cleaned = _clean(entry.value)
        if cleaned:
            return cleaned
    return None


def _best_text(element: PtSituationElement) -> str:
    # Ordre de fallback : résumé court, puis description, puis fallback constant.
    return _first_text(element.summary) or _first_text(element.description) or FALLBACK_TEXT


def _labels(element: PtSituationElement, ref_to_label: dict[str, str]) -> list[str]:
    if element.consequences is None:
        return []
    found: list[str] = []
    for consequence in element.consequences.consequence:
        if consequence.affects is None or consequence.affects.networks is None:
            continue
        for network in consequence.affects.networks.affected_network:
            for affected in network.affected_line:
                ref = affected.line_ref.value if affected.line_ref else None
                label = ref_to_label.get(ref) if ref is not None else None
                if label is not None and label not in found:
                    found.append(label)
    return found


def to_disruptions(
    document: SiriDocument,
    config: DisruptionsConfig,
    now: datetime,
) -> tuple[TransitDisruption, ...]:
    ref_to_label = config.ref_to_label()
    future_window = timedelta(hours=config.future_window_hours)

    by_id: dict[str, TransitDisruption] = {}
    for element in document.situations():
        labels = _labels(element, ref_to_label)
        if not labels:
            continue
        source_id = element.situation_number.value if element.situation_number else None
        if not source_id or source_id in by_id:
            continue

        period = element.validity_period[0] if element.validity_period else None
        valid_from = period.start_time if period else None
        valid_until = period.end_time if period else None

        if valid_until is not None and now > valid_until:
            continue  # expirée
        if valid_from is not None and valid_from > now + future_window:
            continue  # planifiée trop lointaine

        text = _best_text(element)
        by_id[source_id] = TransitDisruption(
            source_id=source_id,
            lines=tuple(sorted(labels)),
            summary=text,
            description=text,
            valid_from=valid_from,
            valid_until=valid_until,
            severity=None,
            planned=element.planned,
        )

    return tuple(by_id[key] for key in sorted(by_id))
