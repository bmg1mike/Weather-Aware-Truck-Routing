"""Polyline encoding, route distances, checkpoint placement and ETAs (spec 6.1). Pure.

Checkpoint miles are measured along the route geometry and scaled so the route's total matches
the provider's reported distance. ETAs interpolate the provider's per-point travel times when
available, otherwise they are proportional to distance [ASSUMPTION].
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections.abc import Sequence
from datetime import timedelta
from itertools import pairwise

from trips.domain import SAMPLING_INTERVALS_MI, Checkpoint, LatLon, RouteOption, SamplingInterval

EARTH_RADIUS_MI = 3958.7613
DROP_FRACTION = 0.25  # drop the last interval checkpoint if within 0.25·d of the destination
_POLYLINE_FACTOR = 1e5


# --- encoded polyline (precision 5, Google algorithm) --------------------------------------------


def _encode_value(value: int) -> str:
    value = ~(value << 1) if value < 0 else value << 1
    chunks = []
    while value >= 0x20:
        chunks.append(chr((0x20 | (value & 0x1F)) + 63))
        value >>= 5
    chunks.append(chr(value + 63))
    return "".join(chunks)


def encode_polyline(points: Sequence[LatLon]) -> str:
    out: list[str] = []
    prev_lat = prev_lon = 0
    for point in points:
        lat, lon = round(point.lat * _POLYLINE_FACTOR), round(point.lon * _POLYLINE_FACTOR)
        out.append(_encode_value(lat - prev_lat))
        out.append(_encode_value(lon - prev_lon))
        prev_lat, prev_lon = lat, lon
    return "".join(out)


def decode_polyline(encoded: str) -> list[LatLon]:
    values: list[int] = []
    result = shift = 0
    for char in encoded:
        byte = ord(char) - 63
        result |= (byte & 0x1F) << shift
        shift += 5
        if byte < 0x20:
            values.append(~(result >> 1) if result & 1 else result >> 1)
            result = shift = 0
    if result or shift or len(values) % 2:
        raise ValueError("Malformed encoded polyline.")
    points: list[LatLon] = []
    lat = lon = 0
    for d_lat, d_lon in zip(values[::2], values[1::2], strict=True):
        lat += d_lat
        lon += d_lon
        points.append(LatLon(lat / _POLYLINE_FACTOR, lon / _POLYLINE_FACTOR))
    return points


# --- distance ------------------------------------------------------------------------------------


def haversine_mi(a: LatLon, b: LatLon) -> float:
    phi1, phi2 = math.radians(a.lat), math.radians(b.lat)
    d_phi = phi2 - phi1
    d_lambda = math.radians(b.lon - a.lon)
    h = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_MI * math.asin(math.sqrt(h))


def cumulative_miles(points: Sequence[LatLon], total_mi: float | None = None) -> list[float]:
    """Distance from the first point to each point; optionally scaled to end at ``total_mi``."""
    cumulative = [0.0]
    for a, b in pairwise(points):
        cumulative.append(cumulative[-1] + haversine_mi(a, b))
    measured = cumulative[-1]
    if total_mi is not None and measured > 0:
        scale = total_mi / measured
        cumulative = [d * scale for d in cumulative]
    return cumulative


# --- checkpoints ---------------------------------------------------------------------------------


def checkpoint_miles(total_mi: float, interval_mi: float) -> list[float]:
    """0, d, 2d, ... strictly before the destination, then the destination itself."""
    miles = []
    k = 0
    while k * interval_mi < total_mi:
        miles.append(k * interval_mi)
        k += 1
    if len(miles) > 1 and total_mi - miles[-1] < DROP_FRACTION * interval_mi:
        miles.pop()
    miles.append(total_mi)
    return miles


def _interpolate(xs: Sequence[float], ys: Sequence[float], x: float) -> tuple[int, float, float]:
    """Index i, fraction f and y at ``x``, where x lies between xs[i] and xs[i+1]."""
    i = min(max(bisect_right(xs, x) - 1, 0), len(xs) - 2)
    span = xs[i + 1] - xs[i]
    frac = 0.0 if span <= 0 else min(max((x - xs[i]) / span, 0.0), 1.0)
    return i, frac, ys[i] + (ys[i + 1] - ys[i]) * frac


def sample_checkpoints(route: RouteOption, interval_mi: SamplingInterval) -> list[Checkpoint]:
    if interval_mi not in SAMPLING_INTERVALS_MI:
        raise ValueError(f"interval_mi must be one of {SAMPLING_INTERVALS_MI}")
    if len(route.points) < 2:
        raise ValueError("A route needs at least two points.")

    cumulative = cumulative_miles(route.points, total_mi=route.distance_mi)
    total = cumulative[-1]
    if route.point_offsets_s is not None:
        offsets: Sequence[float] = route.point_offsets_s
    else:
        offsets = [route.duration_s * d / total if total > 0 else 0.0 for d in cumulative]

    checkpoints: list[Checkpoint] = []
    last_offset = 0.0
    miles = checkpoint_miles(total, interval_mi)
    for index, mile in enumerate(miles):
        if index == 0:
            point, offset = route.points[0], float(offsets[0])
        elif index == len(miles) - 1:
            point, offset = route.points[-1], float(offsets[-1])
        else:
            i, frac, offset = _interpolate(cumulative, offsets, mile)
            a, b = route.points[i], route.points[i + 1]
            point = LatLon(a.lat + (b.lat - a.lat) * frac, a.lon + (b.lon - a.lon) * frac)
        last_offset = max(last_offset, offset)  # ETAs never go backwards
        checkpoints.append(
            Checkpoint(
                index=index,
                point=point,
                mile=mile,
                eta=route.departure + timedelta(seconds=last_offset),
            )
        )
    return checkpoints
