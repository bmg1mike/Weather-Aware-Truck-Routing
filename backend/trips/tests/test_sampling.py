"""Polyline encoding, distances, checkpoint placement and ETAs (spec 6.1)."""

from datetime import UTC, datetime, timedelta

import pytest

from trips.domain import LatLon, RouteOption
from trips.services.sampling import (
    cumulative_miles,
    decode_polyline,
    encode_polyline,
    haversine_mi,
    sample_checkpoints,
)

DEPART = datetime(2026, 11, 25, 12, tzinfo=UTC)
# Google's reference vector for the encoded polyline algorithm.
GOOGLE_POINTS = [LatLon(38.5, -120.2), LatLon(40.7, -120.95), LatLon(43.252, -126.453)]
GOOGLE_ENCODED = "_p~iF~ps|U_ulLnnqC_mqNvxq`@"
MI_PER_DEG_LAT = haversine_mi(LatLon(0, 0), LatLon(1, 0))


def straight_route(
    miles: float,
    *,
    hours: float = 10,
    n_points: int = 201,
    distance_mi: float | None = None,
    offsets: tuple[float, ...] | None = None,
) -> RouteOption:
    """A due-north route along the -100 meridian of the given length."""
    span = miles / MI_PER_DEG_LAT
    points = tuple(LatLon(30 + span * i / (n_points - 1), -100) for i in range(n_points))
    duration = round(hours * 3600)
    return RouteOption(
        id="r1",
        points=points,
        distance_mi=miles if distance_mi is None else distance_mi,
        duration_s=duration,
        departure=DEPART,
        arrival=DEPART + timedelta(seconds=duration),
        point_offsets_s=offsets,
    )


# --- polyline ------------------------------------------------------------------------------------


def test_encode_matches_reference_vector():
    assert encode_polyline(GOOGLE_POINTS) == GOOGLE_ENCODED


def test_decode_matches_reference_vector():
    assert decode_polyline(GOOGLE_ENCODED) == GOOGLE_POINTS


def test_round_trip_keeps_five_decimals():
    points = [LatLon(32.77671, -96.79702), LatLon(-33.86882, 151.20929), LatLon(0, 0)]
    assert decode_polyline(encode_polyline(points)) == points


# --- distance ------------------------------------------------------------------------------------


def test_haversine_known_distance():
    # Dallas to Denver great-circle distance is about 663 miles.
    assert haversine_mi(LatLon(32.7767, -96.7970), LatLon(39.7392, -104.9903)) == pytest.approx(
        663, abs=2
    )


def test_cumulative_miles_scale_to_provider_distance():
    points = [LatLon(30, -100), LatLon(31, -100), LatLon(32, -100)]
    raw = cumulative_miles(points)
    assert raw[0] == 0 and raw[1] == pytest.approx(raw[2] / 2)
    scaled = cumulative_miles(points, total_mi=150)
    assert scaled == pytest.approx([0, 75, 150])


# --- checkpoint placement ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("interval", "expected_miles"),
    [
        (25, [0, 25, 50, 75, 100]),
        (50, [0, 50, 100]),
        (10, [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]),
    ],
)
def test_checkpoints_every_interval_including_both_ends(interval, expected_miles):
    checkpoints = sample_checkpoints(straight_route(100), interval)
    assert [round(c.mile, 6) for c in checkpoints] == expected_miles
    assert [c.index for c in checkpoints] == list(range(len(expected_miles)))


def test_last_interval_checkpoint_within_quarter_interval_of_destination_is_dropped():
    # 106 mi at 25 mi: 100 is within 6.25 mi of the end, so it is dropped.
    assert [c.mile for c in sample_checkpoints(straight_route(106), 25)][-2:] == [
        pytest.approx(75),
        pytest.approx(106),
    ]
    # 107 mi: 100 is 7 mi from the end, more than 6.25, so it stays.
    assert [round(c.mile) for c in sample_checkpoints(straight_route(107), 25)][-2:] == [100, 107]


def test_short_route_has_origin_and_destination():
    checkpoints = sample_checkpoints(straight_route(4), 25)
    assert [round(c.mile, 6) for c in checkpoints] == [0, 4]


def test_checkpoint_positions_lie_on_the_route():
    route = straight_route(100)
    checkpoints = sample_checkpoints(route, 25)
    assert checkpoints[0].point == route.points[0]
    assert checkpoints[-1].point == route.points[-1]
    assert checkpoints[2].point.lat == pytest.approx(30 + 50 / MI_PER_DEG_LAT)
    assert checkpoints[2].point.lon == pytest.approx(-100)


def test_checkpoint_miles_use_the_provider_distance():
    # Geometry measures 100 mi but TomTom reports 110 mi: miles are scaled to the provider's.
    checkpoints = sample_checkpoints(straight_route(100, distance_mi=110), 25)
    assert [round(c.mile, 6) for c in checkpoints] == [0, 25, 50, 75, 100, 110]


# --- ETAs ----------------------------------------------------------------------------------------


def test_eta_is_proportional_without_provider_times():
    checkpoints = sample_checkpoints(straight_route(100, hours=10), 25)
    assert [c.eta - DEPART for c in checkpoints] == [
        timedelta(hours=h) for h in (0, 2.5, 5, 7.5, 10)
    ]


def test_eta_follows_provider_point_times():
    # 3 points 50 mi apart: the first half takes 1 h, the second half 4 h.
    route = straight_route(100, hours=5, n_points=3, offsets=(0, 3600, 18000))
    etas = [c.eta - DEPART for c in sample_checkpoints(route, 25)]
    assert etas == [timedelta(hours=h) for h in (0, 0.5, 1, 3, 5)]


def test_etas_are_monotonic_and_end_at_arrival():
    route = straight_route(737, hours=11.3, n_points=1000)
    checkpoints = sample_checkpoints(route, 10)
    etas = [c.eta for c in checkpoints]
    assert etas == sorted(etas)
    assert etas[-1] == route.arrival


def test_rejects_unknown_interval():
    with pytest.raises(ValueError):
        sample_checkpoints(straight_route(100), 20)  # type: ignore[arg-type]
