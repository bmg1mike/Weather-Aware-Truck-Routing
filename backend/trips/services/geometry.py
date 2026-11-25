"""Route geometry helpers: proximity, overlap and via points. Pure: no I/O, no Django."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from itertools import pairwise

from trips.domain import LatLon
from trips.services.sampling import cumulative_miles, haversine_mi

_BUCKET_DEG = 0.5
_MI_PER_DEG = 69.09  # one degree of latitude (and of longitude at the equator)


def densify(route: Sequence[LatLon], step_mi: float) -> list[LatLon]:
    """Route vertices thinned and filled in so consecutive samples are about ``step_mi`` apart."""
    if not route:
        return []
    samples = [route[0]]
    for a, b in pairwise(route):
        if haversine_mi(samples[-1], b) < step_mi:
            continue
        pieces = math.ceil(haversine_mi(a, b) / step_mi)
        for i in range(1, pieces + 1):
            f = i / pieces
            samples.append(LatLon(a.lat + (b.lat - a.lat) * f, a.lon + (b.lon - a.lon) * f))
    if samples[-1] != route[-1]:
        samples.append(route[-1])
    return samples


class ProximityIndex:
    """Answers "is this point within ``radius_mi`` of any of these routes?" via a spatial hash.

    Routes are sampled every ``min(radius_mi, 2)`` miles, so the answer errs by at most half that.
    """

    def __init__(self, routes: Sequence[Sequence[LatLon]], radius_mi: float) -> None:
        self.radius_mi = radius_mi
        self.buckets: dict[tuple[int, int], list[LatLon]] = defaultdict(list)
        step = min(radius_mi, 2.0)
        for route in routes:
            for p in densify(route, step):
                self.buckets[self._bucket(p)].append(p)

    @staticmethod
    def _bucket(p: LatLon) -> tuple[int, int]:
        return math.floor(p.lat / _BUCKET_DEG), math.floor(p.lon / _BUCKET_DEG)

    def contains(self, p: LatLon) -> bool:
        lat_reach = self.radius_mi / _MI_PER_DEG
        lon_reach = lat_reach / max(math.cos(math.radians(p.lat)), 0.05)
        row, col = self._bucket(p)
        rows = math.ceil(lat_reach / _BUCKET_DEG)
        cols = math.ceil(lon_reach / _BUCKET_DEG)
        for r in range(row - rows, row + rows + 1):
            for c in range(col - cols, col + cols + 1):
                for q in self.buckets.get((r, c), ()):
                    if haversine_mi(p, q) <= self.radius_mi:
                        return True
        return False


OVERLAP_TOLERANCE_MI = 0.5  # parallel carriageways and frontage roads count as the same road
_OVERLAP_SAMPLE_MI = 1.0


def overlap_fraction(candidate: Sequence[LatLon], existing: Sequence[LatLon]) -> float:
    """Share of ``candidate``'s length that runs along ``existing`` (0 to 1)."""
    samples = densify(candidate, _OVERLAP_SAMPLE_MI)
    if not samples:
        return 0.0
    index = ProximityIndex([existing], OVERLAP_TOLERANCE_MI)
    return sum(index.contains(p) for p in samples) / len(samples)


def perpendicular_via_points(route: Sequence[LatLon], offset_mi: float) -> tuple[LatLon, LatLon]:
    """Points ``offset_mi`` left and right of the route's midpoint, perpendicular to the overall
    origin-to-destination direction (spec section 5)."""
    if len(route) < 2:
        raise ValueError("A route needs at least two points.")
    cumulative = cumulative_miles(route)
    half = cumulative[-1] / 2
    mid = route[min(range(len(route)), key=lambda i: abs(cumulative[i] - half))]
    origin, destination = route[0], route[-1]
    cos_lat = max(math.cos(math.radians(mid.lat)), 0.05)
    east = (destination.lon - origin.lon) * cos_lat
    north = destination.lat - origin.lat
    norm = math.hypot(east, north) or 1.0
    east, north = east / norm, north / norm
    # Rotating the heading 90 degrees counter-clockwise points left.
    left_east, left_north = -north, east

    def offset(sign: float) -> LatLon:
        d_lat = sign * left_north * offset_mi / _MI_PER_DEG
        d_lon = sign * left_east * offset_mi / (_MI_PER_DEG * cos_lat)
        return LatLon(mid.lat + d_lat, mid.lon + d_lon)

    return offset(1.0), offset(-1.0)
