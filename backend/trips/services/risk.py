"""Risk thresholds and ``classify`` (spec 6.3). Pure: no I/O, no Django.

All thresholds live in the tables below; ``classify`` only walks them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import NamedTuple

from trips.domain import Driver, RiskLevel


@dataclass(frozen=True, slots=True)
class Band:
    """Values below ``upper`` (or equal to it, when ``closed``) fall in ``level``."""

    level: RiskLevel
    upper: float
    closed: bool = False

    def contains(self, value: float) -> bool:
        return value <= self.upper if self.closed else value < self.upper


# Intervals are half-open on the lower bound. Anything above the last band is No Travel.
# Rain and snow Severe bands are closed at the top: exactly 1.00 in/hr and 3.0 in/hr are Severe.
THRESHOLDS: dict[Driver, tuple[Band, ...]] = {
    "wind": (  # mph
        Band(RiskLevel.LOW, 25),
        Band(RiskLevel.MODERATE, 35),
        Band(RiskLevel.HIGH, 45),
        Band(RiskLevel.SEVERE, 55),
    ),
    "rain": (  # in/hr, rain + showers
        Band(RiskLevel.LOW, 0.10),
        Band(RiskLevel.MODERATE, 0.25),
        Band(RiskLevel.HIGH, 0.50),
        Band(RiskLevel.SEVERE, 1.00, closed=True),
    ),
    "snow": (  # in/hr
        Band(RiskLevel.LOW, 0.5),
        Band(RiskLevel.MODERATE, 1.0),
        Band(RiskLevel.HIGH, 2.0),
        Band(RiskLevel.SEVERE, 3.0, closed=True),
    ),
}


@dataclass(frozen=True, slots=True)
class LoadRule:
    """A wind level that escalates when the load is strictly greater than ``over_lb``."""

    wind_level: RiskLevel
    over_lb: int
    escalated: RiskLevel


# "Greater than": exactly 30,000 lb and exactly 40,000 lb do not escalate.
LOAD_RULES: tuple[LoadRule, ...] = (
    LoadRule(RiskLevel.SEVERE, 30_000, RiskLevel.NO_TRAVEL),
    LoadRule(RiskLevel.HIGH, 40_000, RiskLevel.SEVERE),
)

# When conditions tie on level, the driver is the first in this order.
DRIVER_ORDER: tuple[Driver, ...] = ("wind", "rain", "snow")

# Strip binary floating-point noise (0.07 + 0.03 == 0.09999999999999999) before comparing.
# Six decimals is far below the precision of any forecast value, so no real reading moves.
_NOISE_DECIMALS = 6


class Classification(NamedTuple):
    level: RiskLevel
    driver: Driver


def level_for(condition: Driver, value: float) -> RiskLevel:
    """Level of one condition from the threshold table, before load rules."""
    value = round(value, _NOISE_DECIMALS)
    for band in THRESHOLDS[condition]:
        if band.contains(value):
            return band.level
    return RiskLevel.NO_TRAVEL


def apply_load_rules(wind_level: RiskLevel, load_lb: int) -> RiskLevel:
    for rule in LOAD_RULES:
        if wind_level == rule.wind_level and load_lb > rule.over_lb:
            return rule.escalated
    return wind_level


def classify(wind_mph: float, rain_in_hr: float, snow_in_hr: float, load_lb: int) -> Classification:
    """Checkpoint risk: the highest of wind (after load rules), rain and snow, and its driver."""
    for name, value in (
        ("wind_mph", wind_mph),
        ("rain_in_hr", rain_in_hr),
        ("snow_in_hr", snow_in_hr),
    ):
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} must be a finite, non-negative number, got {value!r}")
    if load_lb < 1:
        raise ValueError(f"load_lb must be positive, got {load_lb!r}")

    levels: dict[Driver, RiskLevel] = {
        "wind": apply_load_rules(level_for("wind", wind_mph), load_lb),
        "rain": level_for("rain", rain_in_hr),
        "snow": level_for("snow", snow_in_hr),
    }
    worst = max(levels.values())
    driver = next(d for d in DRIVER_ORDER if levels[d] == worst)
    return Classification(worst, driver)
