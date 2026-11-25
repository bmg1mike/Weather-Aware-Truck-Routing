"""Route geometry helpers for the fewer-than-three-routes fallback (spec section 5)."""

import pytest

from trips.domain import LatLon
from trips.services.geometry import (
    ProximityIndex,
    in_us,
    overlap_fraction,
    perpendicular_via_points,
)
from trips.services.sampling import haversine_mi

MI_PER_DEG_LAT = haversine_mi(LatLon(0, 0), LatLon(1, 0))


def north(lon: float, miles: float = 300, start_lat: float = 35.0, n: int = 61) -> list[LatLon]:
    span = miles / MI_PER_DEG_LAT
    return [LatLon(start_lat + span * i / (n - 1), lon) for i in range(n)]


# --- overlap -------------------------------------------------------------------------------------


def test_identical_routes_overlap_fully():
    assert overlap_fraction(north(-100), north(-100)) == pytest.approx(1.0, abs=0.01)


def test_parallel_routes_far_apart_do_not_overlap():
    assert overlap_fraction(north(-100), north(-101)) == 0.0  # ~57 miles apart


def test_partial_overlap_is_the_shared_share_of_the_candidate():
    shared = north(-100, miles=150)
    branch_start = shared[-1]
    branch = [LatLon(branch_start.lat, branch_start.lon - 2.0 * i / 30) for i in range(1, 31)]
    candidate = shared + branch  # 150 mi shared, then ~100 mi west
    fraction = overlap_fraction(candidate, north(-100))
    assert 0.5 < fraction < 0.7


def test_roads_a_few_hundred_metres_apart_count_as_overlapping():
    assert overlap_fraction(north(-100.004), north(-100)) > 0.95


# --- via points ----------------------------------------------------------------------------------


def test_via_points_are_perpendicular_to_the_route_at_its_midpoint():
    route = north(-100, miles=500)
    left, right = perpendicular_via_points(route, offset_mi=50)
    mid = route[len(route) // 2]
    # Heading north, left is west and right is east, each 50 mi from the midpoint.
    assert left.lon < mid.lon < right.lon
    assert left.lat == pytest.approx(mid.lat, abs=0.05) and right.lat == pytest.approx(
        mid.lat, abs=0.05
    )
    assert haversine_mi(left, mid) == pytest.approx(50, rel=0.02)
    assert haversine_mi(right, mid) == pytest.approx(50, rel=0.02)


def test_via_points_follow_the_route_direction():
    east = [LatLon(35.0, -110 + 10 * i / 60) for i in range(61)]
    left, right = perpendicular_via_points(east, offset_mi=40)
    assert left.lat > 35.0 > right.lat  # heading east, left is north


# --- proximity and US bounds ---------------------------------------------------------------------


def test_proximity_index():
    index = ProximityIndex([north(-100)], radius_mi=30)
    assert index.contains(LatLon(36.0, -100.3))  # ~17 mi away
    assert not index.contains(LatLon(36.0, -101.0))  # ~56 mi away


@pytest.mark.parametrize(
    ("point", "expected"),
    [
        (LatLon(39.74, -104.99), True),  # Denver
        (LatLon(61.2, -149.9), True),  # Anchorage
        (LatLon(21.3, -157.8), True),  # Honolulu
        (LatLon(19.43, -99.13), False),  # Mexico City
        (LatLon(51.5, -0.12), False),  # London
    ],
)
def test_in_us(point, expected):
    assert in_us(point.lat, point.lon) is expected
