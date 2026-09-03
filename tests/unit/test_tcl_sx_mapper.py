import json
from datetime import UTC, datetime
from pathlib import Path

from eink_dashboard.core.config import DisruptionLine, DisruptionsConfig
from eink_dashboard.providers.tcl_sx.mapper import FALLBACK_TEXT, to_disruptions
from eink_dashboard.providers.tcl_sx.schemas import SiriDocument

FIXTURES = Path(__file__).parent.parent / "fixtures"
# now = 2026-09-03 12:00 Europe/Paris = 10:00Z ; fenêtre future par défaut = 2 h.
NOW = datetime(2026, 9, 3, 10, 0, tzinfo=UTC)

CONFIG = DisruptionsConfig(
    lines=["T2", "D"],
    line_refs=[
        DisruptionLine(label="T2", refs=["ActIV:Line::T2:SYTRAL"]),
        DisruptionLine(label="D", refs=["ActIV:Line::D:SYTRAL"]),
    ],
)


def _synthetic() -> tuple:
    document = SiriDocument.model_validate_json(
        (FIXTURES / "tcl_situation_exchange_t2_d.json").read_text(encoding="utf-8")
    )
    return to_disruptions(document, CONFIG, NOW)


def _by_id() -> dict[str, object]:
    return {d.source_id: d for d in _synthetic()}


def test_active_t2_disruption_is_mapped() -> None:
    entry = _by_id()["SYNTH_T2_ACTIVE"]
    assert entry.lines == ("T2",)
    assert "Jean Macé" in entry.description


def test_active_metro_d_disruption_is_mapped() -> None:
    entry = _by_id()["SYNTH_D_ACTIVE"]
    assert entry.lines == ("D",)
    # Le HTML est retiré et les espaces normalisés.
    assert entry.description == "Station Guillotière non desservie. Bus relais."


def test_situation_touching_t2_and_d_keeps_both_labels() -> None:
    assert _by_id()["SYNTH_T2_D_BOTH"].lines == ("D", "T2")


def test_unfollowed_line_is_ignored() -> None:
    assert "SYNTH_BUS_UNFOLLOWED" not in _by_id()


def test_expired_situation_is_ignored() -> None:
    assert "SYNTH_EXPIRED" not in _by_id()


def test_far_future_situation_is_ignored_but_near_future_is_kept() -> None:
    ids = _by_id()
    assert "SYNTH_FUTURE_FAR" not in ids
    assert "SYNTH_FUTURE_NEAR" in ids


def test_missing_text_falls_back_to_constant() -> None:
    assert _by_id()["SYNTH_NO_TEXT"].description == FALLBACK_TEXT


def test_validity_period_without_end_time_is_supported() -> None:
    entry = _by_id()["SYNTH_NO_END"]
    assert entry.valid_until is None
    assert entry.valid_from is not None


def test_duplicate_situation_number_is_deduplicated() -> None:
    entries = [d for d in _synthetic() if d.source_id == "SYNTH_T2_ACTIVE"]
    assert len(entries) == 1
    assert "DOUBLON" not in entries[0].description


def test_result_is_sorted_by_source_id_for_stable_images() -> None:
    ids = [d.source_id for d in _synthetic()]
    assert ids == sorted(ids)


def test_real_capture_produces_stable_domain_objects() -> None:
    raw = json.loads((FIXTURES / "tcl_situation_exchange.json").read_text(encoding="utf-8"))
    document = SiriDocument.model_validate(raw)
    disruptions = to_disruptions(document, CONFIG, NOW)

    # La capture réelle ne contient que des perturbations métro D (aucune T2 active).
    assert disruptions
    assert all(d.lines == ("D",) for d in disruptions)
    assert all(d.description for d in disruptions)
