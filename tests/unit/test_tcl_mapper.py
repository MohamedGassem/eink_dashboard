import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from eink_dashboard.core.config import TclStop
from eink_dashboard.providers.tcl.mapper import to_stop_boards
from eink_dashboard.providers.tcl.schemas import TCL_FIELDS, PassageFeed, PassageRecord

FIXTURES = Path(__file__).parent.parent / "fixtures"
PARIS = ZoneInfo("Europe/Paris")
NOW = datetime(2026, 9, 2, 8, 0, tzinfo=PARIS)


def test_fixture_contains_every_mapped_field() -> None:
    payload = json.loads((FIXTURES / "tcl_passages.json").read_text(encoding="utf-8"))
    record = payload["values"][0]

    missing = [api_name for api_name in TCL_FIELDS.values() if api_name not in record]
    assert missing == [], f"champs absents de la capture: {missing}"


def test_tcl_fields_matches_schema_aliases() -> None:
    for internal, api_name in TCL_FIELDS.items():
        assert PassageRecord.model_fields[internal].alias == api_name


def test_schema_parses_the_real_capture() -> None:
    feed = PassageFeed.model_validate_json(
        (FIXTURES / "tcl_passages.json").read_text(encoding="utf-8")
    )

    assert feed.nb_results == 20
    assert len(feed.values) == 20
    first = feed.values[0]
    assert first.stop_id == "30101"  # coercé depuis un entier
    assert first.line == "A"
    assert first.expected_at.tzinfo is not None  # localisé sur Europe/Paris


def _stop(lines: tuple[str, ...] = ("A",), directions: tuple[str, ...] = ()) -> TclStop:
    return TclStop(name="Bellecour", stop_id="1234", lines=list(lines), directions=list(directions))


def record(line: str, direction: str, minutes: int, kind: str = "E") -> PassageRecord:
    return PassageRecord(
        stop_id="1234",
        line=line,
        direction=direction,
        expected_at=NOW + timedelta(minutes=minutes),
        kind=kind,
    )


def test_departures_are_sorted_by_time() -> None:
    feed = PassageFeed(values=[record("A", "Vaulx", 9), record("A", "Vaulx", 2)])
    board = to_stop_boards(feed, _stop())

    assert [departure.minutes_until(NOW) for departure in board.departures] == [2, 9]


def test_stop_name_comes_from_configuration() -> None:
    feed = PassageFeed(values=[record("A", "Vaulx", 2)])
    board = to_stop_boards(feed, _stop())

    assert board.stop_name == "Bellecour"


def test_line_filter_excludes_other_lines() -> None:
    feed = PassageFeed(values=[record("A", "Vaulx", 2), record("D", "Venissieux", 3)])
    board = to_stop_boards(feed, _stop(lines=("A",)))

    assert [departure.line for departure in board.departures] == ["A"]


def test_all_configured_lines_are_kept() -> None:
    feed = PassageFeed(values=[record("A", "Vaulx", 2), record("D", "Venissieux", 3)])
    board = to_stop_boards(feed, _stop(lines=("A", "D")))

    assert {departure.line for departure in board.departures} == {"A", "D"}


def test_direction_filter_is_a_case_insensitive_substring() -> None:
    feed = PassageFeed(
        values=[record("A", "VAULX-EN-VELIN LA SOIE", 2), record("A", "Perrache", 3)]
    )
    board = to_stop_boards(feed, _stop(lines=("A",), directions=("vaulx",)))

    assert [departure.direction for departure in board.departures] == ["VAULX-EN-VELIN LA SOIE"]


def test_empty_direction_filter_keeps_every_direction() -> None:
    feed = PassageFeed(values=[record("A", "Vaulx", 2), record("A", "Perrache", 3)])
    board = to_stop_boards(feed, _stop(lines=("A",)))

    assert len(board.departures) == 2


def test_limit_caps_the_number_of_departures() -> None:
    feed = PassageFeed(values=[record("A", "Vaulx", minutes) for minutes in (1, 2, 3, 4, 5, 6)])
    board = to_stop_boards(feed, _stop(), limit=4)

    assert len(board.departures) == 4


def test_no_passage_produces_an_empty_but_available_board() -> None:
    board = to_stop_boards(PassageFeed(), _stop())

    assert board.stop_name == "Bellecour"
    assert board.departures == ()
    assert board.available is True


def test_theoretical_passage_is_not_realtime() -> None:
    feed = PassageFeed(values=[record("A", "Vaulx", 2, kind="T")])
    board = to_stop_boards(feed, _stop())

    assert board.departures[0].is_realtime is False


def test_estimated_passage_is_realtime() -> None:
    feed = PassageFeed(values=[record("A", "Vaulx", 2, kind="E")])
    board = to_stop_boards(feed, _stop())

    assert board.departures[0].is_realtime is True
