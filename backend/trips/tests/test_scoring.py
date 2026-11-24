"""Segment miles, route summary and ranking (spec 6.4, 6.5)."""

from datetime import UTC, datetime

import pytest

from trips.domain import Checkpoint, LatLon, RiskLevel
from trips.services.scoring import (
    RouteScore,
    RouteSummary,
    no_travel_stretches,
    rank_routes,
    segments,
    summarize,
)

L, M, H, S, N = (
    RiskLevel.LOW,
    RiskLevel.MODERATE,
    RiskLevel.HIGH,
    RiskLevel.SEVERE,
    RiskLevel.NO_TRAVEL,
)
ETA = datetime(2026, 11, 25, 12, tzinfo=UTC)


def cps(*points: tuple[float, RiskLevel | None]) -> list[Checkpoint]:
    """Checkpoints from (mile, level) pairs; level None means no forecast."""
    return [
        Checkpoint(index=i, point=LatLon(0, 0), mile=mile, eta=ETA, level=level)
        for i, (mile, level) in enumerate(points)
    ]


# --- segments ------------------------------------------------------------------------------------


def test_segment_takes_the_higher_endpoint_level():
    result = segments(cps((0, L), (25, H), (50, M)))
    assert [(s.start_mi, s.end_mi, s.level) for s in result] == [(0, 25, H), (25, 50, H)]


def test_segment_touching_an_unknown_checkpoint_is_unknown():
    result = segments(cps((0, S), (10, None), (20, L)))
    assert [s.level for s in result] == [None, None]


# --- summary -------------------------------------------------------------------------------------


def test_miles_by_level_sum_to_route_distance():
    summary = summarize(cps((0, L), (25, M), (50, M), (75, S), (82.4, L)))
    assert sum(summary.miles_by_level.values()) == pytest.approx(82.4)
    assert summary.miles_by_level == {
        L: 0,
        M: pytest.approx(50),
        H: 0,
        S: pytest.approx(32.4),
        N: 0,
    }
    assert summary.unknown_mi == 0


def test_average_risk_is_distance_weighted():
    # 10 mi Low (0) then 30 mi Severe (3): (0*10 + 3*30) / 40 = 2.25, not the plain mean 1.5.
    assert summarize(cps((0, L), (10, L), (40, S))).avg_risk == 2.25


def test_average_risk_is_rounded_to_two_decimals():
    # 20 mi Low, 10 mi Moderate: 10/30 = 0.333...
    assert summarize(cps((0, L), (10, L), (20, L), (30, M))).avg_risk == 0.33


def test_unknown_miles_are_excluded_from_levels_and_average():
    summary = summarize(cps((0, L), (10, L), (20, None), (30, L)))
    assert summary.miles_by_level[L] == 10
    assert summary.unknown_mi == 20
    assert summary.avg_risk == 0.0
    assert summary.unknown_checkpoints == 1


def test_route_with_no_forecast_has_no_average_rather_than_low():
    summary = summarize(cps((0, None), (25, None)))
    assert summary.avg_risk is None
    assert sum(summary.miles_by_level.values()) == 0
    assert summary.unknown_mi == 25
    assert summary.worst_checkpoint is None


def test_worst_checkpoint_is_the_first_at_the_highest_level():
    assert summarize(cps((0, L), (10, S), (20, M), (30, S))).worst_checkpoint == 1


def test_zero_length_segment_is_allowed():
    summary = summarize(cps((0, L), (10, H), (10, H), (20, L)))
    assert summary.miles_by_level[H] == 20


@pytest.mark.parametrize(
    "points", [[(0, L)], [], [(0, L), (20, L), (10, L)]], ids=["one", "none", "decreasing"]
)
def test_summarize_rejects_unusable_checkpoints(points):
    with pytest.raises(ValueError):
        summarize(cps(*points))


# --- ranking -------------------------------------------------------------------------------------


def score(
    route_id: str,
    *,
    no_travel: float = 0,
    severe: float = 0,
    high: float = 0,
    avg: float | None = 0.5,
    minutes: float = 600,
) -> RouteScore:
    miles = {L: 100.0, M: 0.0, H: high, S: severe, N: no_travel}
    summary = RouteSummary(
        miles_by_level=miles,
        unknown_mi=0,
        avg_risk=avg,
        unknown_checkpoints=0,
        worst_checkpoint=0,
    )
    return RouteScore(
        id=route_id, name=f"Route {route_id}", duration_s=round(minutes * 60), summary=summary
    )


def order(*scores: RouteScore) -> list[str]:
    return [r.route.id for r in rank_routes(scores).routes]


def test_no_travel_miles_rank_ahead_of_severe_miles():
    assert order(score("A", no_travel=1, severe=0), score("B", severe=200)) == ["B", "A"]


def test_severe_miles_decide_before_high_miles():
    assert order(score("A", severe=5, high=0), score("B", severe=0, high=300)) == ["B", "A"]


def test_high_miles_decide_before_average_risk():
    assert order(score("A", high=10, avg=0.1), score("B", high=0, avg=1.9)) == ["B", "A"]


def test_average_risk_decides_before_travel_time():
    assert order(score("A", avg=0.6, minutes=500), score("B", avg=0.4, minutes=700)) == ["B", "A"]


def test_travel_time_is_the_last_tiebreaker():
    assert order(score("A", minutes=620), score("B", minutes=600)) == ["B", "A"]


def test_miles_are_rounded_to_a_tenth_before_comparing():
    # 10.04 and 10.01 both round to 10.0, so Severe ties and High decides.
    assert order(score("A", severe=10.01, high=5), score("B", severe=10.04, high=0)) == ["B", "A"]
    # 10.06 rounds to 10.1, so Severe decides.
    assert order(score("A", severe=10.06, high=0), score("B", severe=10.04, high=5)) == ["B", "A"]


def test_complete_tie_keeps_provider_order():
    assert order(score("A"), score("B"), score("C")) == ["A", "B", "C"]


def test_route_without_any_forecast_ranks_after_equal_routes_with_one():
    assert order(score("A", avg=None, minutes=300), score("B", avg=3.9)) == ["B", "A"]


def test_ranks_and_recommendation():
    result = rank_routes([score("A", severe=3), score("B"), score("C", severe=1)])
    assert [(r.route.id, r.rank) for r in result.routes] == [("B", 1), ("C", 2), ("A", 3)]
    assert result.recommended.route.id == "B"
    assert result.no_safe_route is False


def test_no_safe_route_when_every_route_has_no_travel_miles():
    result = rank_routes([score("A", no_travel=12), score("B", no_travel=4)])
    assert result.recommended.route.id == "B"
    assert result.no_safe_route is True
    assert result.recommended.reason.startswith("Least bad:")


def test_rank_routes_requires_a_route():
    with pytest.raises(ValueError):
        rank_routes([])


# --- reasons -------------------------------------------------------------------------------------


def reasons(*scores: RouteScore) -> dict[str, str]:
    return {r.route.id: r.reason for r in rank_routes(scores).routes}


def test_reason_names_the_deciding_key_and_the_time_trade_off():
    text = reasons(score("A", severe=0, minutes=618), score("B", severe=42, minutes=600))
    assert text["A"] == "Recommended: fewest Severe miles (0.0 vs 42.0 on Route B), 18 min slower."
    assert text["B"] == "More Severe miles than Route A (42.0 vs 0.0), 18 min faster."


def test_reason_for_average_risk_tiebreak():
    text = reasons(score("A", avg=0.29), score("B", avg=0.41))
    assert text["A"] == (
        "Recommended: same No Travel, Severe and High miles as Route B, "
        "lower average risk (0.29 vs 0.41)."
    )
    assert text["B"] == (
        "Same No Travel, Severe and High miles as Route A, higher average risk (0.41 vs 0.29)."
    )


def test_reason_for_travel_time_tiebreak_uses_hours():
    text = reasons(score("A", minutes=600), score("B", minutes=665))
    assert text["A"] == "Recommended: same risk as Route B, 1 h 05 min faster."
    assert text["B"] == "Same risk as Route A, 1 h 05 min slower."


def test_reason_for_complete_tie():
    text = reasons(score("A"), score("B"))
    assert text["A"] == "Recommended: ties Route B on risk and travel time."
    assert (
        text["B"]
        == "Ties Route A on risk and travel time; listed after it by the routing provider."
    )


def test_reason_for_a_route_without_forecast():
    text = reasons(score("A"), score("B", avg=None))
    assert text["B"] == "Same No Travel, Severe and High miles as Route A, no forecast to compare."


def test_reason_for_a_single_route():
    assert reasons(score("A")) == {"A": "Recommended: the only route available."}


# --- blocking stretch ----------------------------------------------------------------------------


def test_no_travel_stretches_merge_adjacent_segments():
    route = cps((0, L), (10, N), (20, N), (30, L), (40, L), (50, L), (60, N), (70, L))
    assert no_travel_stretches(segments(route)) == [(0, 30), (50, 70)]


def test_no_travel_stretches_empty_when_safe():
    assert no_travel_stretches(segments(cps((0, L), (10, S)))) == []


def test_reason_for_sub_minute_travel_time_tiebreak():
    text = reasons(score("A", minutes=600), score("B", minutes=600.3))
    assert text["A"] == "Recommended: same risk as Route B, under a minute faster."
    assert text["B"] == "Same risk as Route A, under a minute slower."
