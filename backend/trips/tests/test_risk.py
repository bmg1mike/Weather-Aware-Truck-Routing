"""Risk classification (spec 6.3), including every boundary listed in spec section 11."""

import math

import pytest

from trips.domain import RiskLevel
from trips.services.risk import classify

L, M, H, S, N = (
    RiskLevel.LOW,
    RiskLevel.MODERATE,
    RiskLevel.HIGH,
    RiskLevel.SEVERE,
    RiskLevel.NO_TRAVEL,
)
LIGHT_LOAD = 20_000


@pytest.mark.parametrize(
    ("wind", "expected"),
    [(0, L), (24.9, L), (25, M), (34.9, M), (35, H), (44.9, H), (45, S), (54.9, S), (55, N)],
)
def test_wind_boundaries(wind, expected):
    assert classify(wind, 0, 0, LIGHT_LOAD) == (expected, "wind")


@pytest.mark.parametrize(
    ("rain", "expected"),
    [
        (0.09, L),
        (0.10, M),
        (0.249, M),
        (0.25, H),
        (0.499, H),
        (0.50, S),
        (1.00, S),  # Severe band is closed at the top
        (1.01, N),
    ],
)
def test_rain_boundaries(rain, expected):
    level, _ = classify(0, rain, 0, LIGHT_LOAD)
    assert level == expected


@pytest.mark.parametrize(
    ("snow", "expected"),
    [
        (0.49, L),
        (0.5, M),
        (0.99, M),
        (1.0, H),
        (1.99, H),
        (2.0, S),
        (3.0, S),  # Severe band is closed at the top
        (3.01, N),
    ],
)
def test_snow_boundaries(snow, expected):
    level, _ = classify(0, 0, snow, LIGHT_LOAD)
    assert level == expected


def test_float_noise_does_not_cross_a_boundary():
    rain = 0.01 + 0.09  # rain + showers == 0.09999999999999999 in binary floating point
    assert rain != 0.10
    assert classify(0, rain, 0, LIGHT_LOAD) == (M, "rain")


# --- load rules ----------------------------------------------------------------------------------


@pytest.mark.parametrize("wind", [45, 50, 54.9])
@pytest.mark.parametrize(("load", "expected"), [(30_000, S), (30_001, N)])
def test_load_escalation_at_severe_wind(wind, load, expected):
    assert classify(wind, 0, 0, load) == (expected, "wind")


@pytest.mark.parametrize("wind", [35, 40, 44.9])
@pytest.mark.parametrize(("load", "expected"), [(40_000, H), (40_001, S)])
def test_load_escalation_at_high_wind(wind, load, expected):
    assert classify(wind, 0, 0, load) == (expected, "wind")


@pytest.mark.parametrize("load", [1, 30_000, 40_001, 80_000])
def test_no_travel_wind_ignores_load(load):
    assert classify(55, 0, 0, load) == (N, "wind")


@pytest.mark.parametrize("wind", [0, 24.9, 25, 34.9])
def test_load_never_escalates_low_or_moderate_wind(wind):
    assert classify(wind, 0, 0, 80_000) == classify(wind, 0, 0, 1)


def test_load_does_not_escalate_rain_or_snow():
    assert classify(0, 0.6, 0, 80_000) == (S, "rain")
    assert classify(0, 0, 2.5, 80_000) == (S, "snow")


# --- max of conditions and driver ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("wind", "rain", "snow", "expected"),
    [
        (30, 0.30, 0, (H, "rain")),  # rain High beats wind Moderate
        (40, 0.12, 0.6, (H, "wind")),  # wind High beats rain and snow Moderate
        (10, 0.0, 2.2, (S, "snow")),
        (10, 1.5, 3.5, (N, "rain")),  # both No Travel: tie order wind, rain, snow
        (30, 0.10, 0.5, (M, "wind")),  # three-way tie at Moderate
        (0, 0.0, 0.0, (L, "wind")),
    ],
)
def test_highest_condition_wins_with_deterministic_driver(wind, rain, snow, expected):
    assert classify(wind, rain, snow, LIGHT_LOAD) == expected


def test_load_escalated_wind_competes_after_escalation():
    # Wind 40 mph is High; with 40,001 lb it becomes Severe and outranks High rain.
    assert classify(40, 0.30, 0, 40_001) == (S, "wind")
    assert classify(40, 0.30, 0, 40_000) == (H, "wind")  # tie at High, wind first


# --- invalid inputs ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [(math.nan, 0, 0, 1), (0, math.inf, 0, 1), (-1, 0, 0, 1), (0, 0, -0.1, 1), (0, 0, 0, 0)],
)
def test_rejects_values_that_cannot_be_weather(args):
    with pytest.raises(ValueError):
        classify(*args)
