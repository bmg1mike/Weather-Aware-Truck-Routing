from datetime import UTC, datetime

from trips.domain import Checkpoint, LatLon, RiskLevel


def test_risk_levels_are_ordered_scores():
    assert [level.value for level in RiskLevel] == [0, 1, 2, 3, 4]
    assert [level.slug for level in RiskLevel] == ["low", "moderate", "high", "severe", "no_travel"]


def test_checkpoint_without_forecast_is_unknown_not_low():
    checkpoint = Checkpoint(index=0, point=LatLon(32.7, -96.8), mile=0, eta=datetime.now(UTC))
    assert checkpoint.level is None
    assert checkpoint.level_slug == "unknown"
