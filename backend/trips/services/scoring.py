"""Segment miles, route summary and ranking (spec 6.4, 6.5). Pure: no I/O, no Django.

Unknown-forecast policy: a segment with an ``unknown`` endpoint is itself unknown. Its miles are
reported as ``unknown_mi`` and excluded from ``miles_by_level`` and the average, so missing data
never counts as Low. A route with no known miles has ``avg_risk = None``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

from trips.domain import Checkpoint, RiskLevel

MILES_DECIMALS = 1  # miles are rounded to 0.1 before comparing, so float noise cannot decide
AVG_DECIMALS = 2


@dataclass(frozen=True, slots=True)
class Segment:
    start_mi: float
    end_mi: float
    level: RiskLevel | None
    """Higher of the two endpoint levels, or None if either endpoint has no forecast."""

    @property
    def length_mi(self) -> float:
        return self.end_mi - self.start_mi


@dataclass(frozen=True, slots=True)
class RouteSummary:
    miles_by_level: dict[RiskLevel, float]
    unknown_mi: float
    avg_risk: float | None
    unknown_checkpoints: int
    worst_checkpoint: int | None
    """Index of the first checkpoint at the highest known level."""


@dataclass(frozen=True, slots=True)
class RouteScore:
    id: str
    name: str
    """Display name used in reason sentences, e.g. "Route B"."""
    duration_s: int
    summary: RouteSummary


@dataclass(frozen=True, slots=True)
class RankedRoute:
    route: RouteScore
    rank: int
    reason: str


@dataclass(frozen=True, slots=True)
class Ranking:
    routes: list[RankedRoute]
    """Best first. ``routes[0]`` is the recommendation."""
    no_safe_route: bool
    """True when even the recommended route has No Travel miles (it is then the least bad)."""

    @property
    def recommended(self) -> RankedRoute:
        return self.routes[0]


# --- segments and summary ------------------------------------------------------------------------


def segments(checkpoints: Sequence[Checkpoint]) -> list[Segment]:
    if len(checkpoints) < 2:
        raise ValueError("A route needs at least two checkpoints (origin and destination).")
    result = []
    for start, end in pairwise(checkpoints):
        if end.mile < start.mile:
            raise ValueError("Checkpoint miles must not decrease along the route.")
        level = None if start.level is None or end.level is None else max(start.level, end.level)
        result.append(Segment(start.mile, end.mile, level))
    return result


def summarize(checkpoints: Sequence[Checkpoint]) -> RouteSummary:
    miles = dict.fromkeys(RiskLevel, 0.0)
    unknown_mi = 0.0
    for segment in segments(checkpoints):
        if segment.level is None:
            unknown_mi += segment.length_mi
        else:
            miles[segment.level] += segment.length_mi

    known_mi = sum(miles.values())
    avg_risk = (
        round(sum(level * mi for level, mi in miles.items()) / known_mi, AVG_DECIMALS)
        if known_mi > 0
        else None
    )
    known = [cp for cp in checkpoints if cp.level is not None]
    worst = max(known, key=lambda cp: cp.level or 0).index if known else None
    return RouteSummary(
        miles_by_level=miles,
        unknown_mi=unknown_mi,
        avg_risk=avg_risk,
        unknown_checkpoints=len(checkpoints) - len(known),
        worst_checkpoint=worst,
    )


def no_travel_stretches(route_segments: Sequence[Segment]) -> list[tuple[float, float]]:
    """Contiguous No Travel mile ranges, for the "no safe route" banner."""
    stretches: list[tuple[float, float]] = []
    for segment in route_segments:
        if segment.level != RiskLevel.NO_TRAVEL:
            continue
        if stretches and stretches[-1][1] == segment.start_mi:
            stretches[-1] = (stretches[-1][0], segment.end_mi)
        else:
            stretches.append((segment.start_mi, segment.end_mi))
    return stretches


# --- ranking -------------------------------------------------------------------------------------

# Ranking key, in order (spec 6.5). No Travel ranks ahead of Severe [ASSUMPTION].
_RANKED_LEVELS = (RiskLevel.NO_TRAVEL, RiskLevel.SEVERE, RiskLevel.HIGH)
_LEVEL_NAMES = {
    RiskLevel.NO_TRAVEL: "No Travel",
    RiskLevel.SEVERE: "Severe",
    RiskLevel.HIGH: "High",
}
_AVG_KEY = len(_RANKED_LEVELS)
_TIME_KEY = _AVG_KEY + 1


def _rank_key(route: RouteScore) -> tuple[float, ...]:
    summary = route.summary
    miles = tuple(round(summary.miles_by_level[lvl], MILES_DECIMALS) for lvl in _RANKED_LEVELS)
    # No forecast at all is not "no risk": it sorts after any route with a known average.
    avg = math.inf if summary.avg_risk is None else summary.avg_risk
    return (*miles, avg, route.duration_s)


def rank_routes(routes: Sequence[RouteScore]) -> Ranking:
    """Sort best first. Python's sort is stable, so full ties keep the provider's order."""
    if not routes:
        raise ValueError("At least one route is required.")
    ordered = sorted(routes, key=_rank_key)
    best = ordered[0]
    no_safe_route = _rank_key(best)[0] > 0
    ranked = [
        RankedRoute(route=route, rank=i, reason=_reason(route, ordered, no_safe_route))
        for i, route in enumerate(ordered, start=1)
    ]
    return Ranking(routes=ranked, no_safe_route=no_safe_route)


# --- reason sentences ----------------------------------------------------------------------------


def _format_duration(seconds: float) -> str:
    minutes = round(abs(seconds) / 60)
    if minutes == 0:
        return "under a minute"
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    return f"{hours} h {rest:02d} min" if rest else f"{hours} h"


def _time_clause(route: RouteScore, other: RouteScore) -> str:
    diff = route.duration_s - other.duration_s
    if round(abs(diff) / 60) == 0:
        return ""
    return f", {_format_duration(diff)} {'slower' if diff > 0 else 'faster'}"


def _deciding_key(a: RouteScore, b: RouteScore) -> int | None:
    for i, (x, y) in enumerate(zip(_rank_key(a), _rank_key(b), strict=True)):
        if x != y:
            return i
    return None


def _reason(route: RouteScore, ordered: Sequence[RouteScore], no_safe_route: bool) -> str:
    """One sentence on why ``route`` ranked where it did: the winner against the runner-up,
    every other route against the winner."""
    is_best = route is ordered[0]
    prefix = "Least bad: " if no_safe_route else "Recommended: "
    if len(ordered) == 1:
        return f"{prefix}the only route available."
    other = ordered[1] if is_best else ordered[0]
    key = _deciding_key(route, other)
    mine, theirs = route.summary, other.summary

    if key is None:
        if is_best:
            return f"{prefix}ties {other.name} on risk and travel time."
        return (
            f"Ties {other.name} on risk and travel time; listed after it by the routing provider."
        )

    if key < _AVG_KEY:
        level = _RANKED_LEVELS[key]
        a = round(mine.miles_by_level[level], MILES_DECIMALS)
        b = round(theirs.miles_by_level[level], MILES_DECIMALS)
        name = _LEVEL_NAMES[level]
        time = _time_clause(route, other)
        if is_best:
            return f"{prefix}fewest {name} miles ({a:.1f} vs {b:.1f} on {other.name}){time}."
        return f"More {name} miles than {other.name} ({a:.1f} vs {b:.1f}){time}."

    if key == _AVG_KEY:
        same = f"same No Travel, Severe and High miles as {other.name}"
        time = _time_clause(route, other)
        if mine.avg_risk is None or theirs.avg_risk is None:
            detail = "which has no forecast to compare" if is_best else "no forecast to compare"
        else:
            direction = "lower" if is_best else "higher"
            detail = f"{direction} average risk ({mine.avg_risk:.2f} vs {theirs.avg_risk:.2f})"
        if is_best:
            return f"{prefix}{same}, {detail}{time}."
        return f"{same[0].upper()}{same[1:]}, {detail}{time}."

    duration = _format_duration(route.duration_s - other.duration_s)
    if is_best:
        return f"{prefix}same risk as {other.name}, {duration} faster."
    return f"Same risk as {other.name}, {duration} slower."
