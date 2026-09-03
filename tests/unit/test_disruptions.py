from datetime import UTC, datetime, timedelta

from eink_dashboard.domain.disruptions import TransitDisruption

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


def _disruption(valid_from: datetime | None, valid_until: datetime | None) -> TransitDisruption:
    return TransitDisruption(
        source_id="s1",
        lines=("T2",),
        summary="Trafic perturbé",
        description="Trafic perturbé entre Jean Macé et Perrache.",
        valid_from=valid_from,
        valid_until=valid_until,
        severity=None,
        planned=None,
    )


def test_is_active_without_dates_is_always_active() -> None:
    assert _disruption(None, None).is_active(NOW) is True


def test_is_active_before_start() -> None:
    assert _disruption(NOW + timedelta(hours=1), None).is_active(NOW) is False


def test_is_active_during_period() -> None:
    assert _disruption(NOW - timedelta(hours=1), NOW + timedelta(hours=1)).is_active(NOW) is True


def test_is_active_after_end() -> None:
    assert _disruption(None, NOW - timedelta(hours=1)).is_active(NOW) is False


def test_is_active_start_without_end() -> None:
    assert _disruption(NOW - timedelta(hours=1), None).is_active(NOW) is True


def test_is_active_end_without_start() -> None:
    assert _disruption(None, NOW + timedelta(hours=1)).is_active(NOW) is True
