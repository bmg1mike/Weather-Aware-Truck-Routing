"""Corridor grid and the 49 hourly heatmap frames (spec section 7, plan phase 5)."""

from datetime import UTC, datetime, timedelta

import pytest
from django.core.cache.backends.locmem import LocMemCache

from trips.domain import LatLon, RiskLevel
from trips.errors import BudgetExceeded
from trips.services.heatmap import HOURS, HeatmapBuilder, corridor_grid
from trips.services.sampling import haversine_mi
from trips.services.weather import HourValues, WeatherLookup
from trips.tests.test_planner import CALM, FakeWeather

START = datetime(2026, 11, 25, 12, 20, tzinfo=UTC)
# Dallas to Denver as a straight line, densified.
LINE = [LatLon(32.8 + 6.9 * i / 200, -96.8 - 8.2 * i / 200) for i in range(201)]
BBOX = (-105.5, 32.3, -96.3, 40.2)


def distance_to_line(point: LatLon, line=LINE) -> float:
    return min(haversine_mi(point, p) for p in line)


# --- grid -----------------------------------------------------------------------------------------


def test_grid_has_at_most_200_points_on_the_tenth_degree_lattice():
    grid = corridor_grid(BBOX, [LINE])
    assert 0 < len(grid.points) <= 200
    for p in grid.points:
        assert round(p.lat * 10) == pytest.approx(p.lat * 10, abs=1e-9)
        assert round(p.lon * 10) == pytest.approx(p.lon * 10, abs=1e-9)


def test_grid_points_lie_inside_the_corridor_and_bbox():
    grid = corridor_grid(BBOX, [LINE])
    for p in grid.points:
        assert BBOX[0] <= p.lon <= BBOX[2] and BBOX[1] <= p.lat <= BBOX[3]
        assert distance_to_line(p) <= 30 + 1  # buffer plus route-sampling tolerance


def test_grid_is_a_regular_lattice_at_the_reported_spacing():
    grid = corridor_grid(BBOX, [LINE])
    assert grid.spacing_deg >= 0.3
    for p in grid.points:
        assert (p.lat / grid.spacing_deg) == pytest.approx(
            round(p.lat / grid.spacing_deg), abs=1e-6
        )
        assert (p.lon / grid.spacing_deg) == pytest.approx(
            round(p.lon / grid.spacing_deg), abs=1e-6
        )


def test_spacing_starts_at_0_3_and_widens_in_0_1_steps_to_fit():
    short = [LatLon(39.0, -105.0), LatLon(39.5, -104.5)]
    assert corridor_grid((-106, 38, -103, 41), [short]).spacing_deg == pytest.approx(0.3)
    # Los Angeles to New York: far too many points at 0.3 degree.
    coast = [LatLon(34.0 + 6.7 * i / 400, -118.2 + 44.2 * i / 400) for i in range(401)]
    coast_bbox = (-119.0, 33.5, -73.5, 41.2)
    long_trip = corridor_grid(coast_bbox, [coast])
    assert long_trip.spacing_deg > 0.3
    assert len(long_trip.points) <= 200
    assert round(long_trip.spacing_deg * 10) == pytest.approx(long_trip.spacing_deg * 10)
    # One step finer would have exceeded the cap.
    finer_start = round(long_trip.spacing_deg - 0.1, 1)
    finer = corridor_grid(coast_bbox, [coast], start_spacing_deg=finer_start, max_points=10_000)
    assert finer.spacing_deg == finer_start and len(finer.points) > 200


def test_grid_order_is_row_major_south_to_north_then_west_to_east():
    points = corridor_grid(BBOX, [LINE]).points
    assert points == sorted(points, key=lambda p: (p.lat, p.lon))


def test_corridor_too_large_for_the_budget_is_an_actionable_error():
    with pytest.raises(BudgetExceeded):
        corridor_grid(BBOX, [LINE], max_points=3)


# --- frames ---------------------------------------------------------------------------------------


def builder(conditions=lambda c, h: CALM, *, name, missing=(), wind_source="sustained"):
    weather = FakeWeather(conditions, missing)
    lookup = WeatherLookup(weather, LocMemCache(name, {}))
    return HeatmapBuilder(lookup, wind_source=wind_source), weather


@pytest.fixture
def name(request):
    return request.node.nodeid


CELLS = [LatLon(35.0, -100.0), LatLon(35.3, -100.0)]


def test_builds_49_departure_relative_frames_in_grid_order(name):
    frames = builder(
        lambda c, h: HourValues(10.0 if c == CELLS[0] else 30.0, 0, 0, 0, 0), name=name
    )[0].build(CELLS, START, load_lb=20_000)
    assert HOURS == 49
    assert len(frames.risk) == len(frames.wind) == len(frames.rain) == len(frames.snow) == 49
    assert all(len(frame) == 2 for frame in frames.risk)
    assert frames.risk[0] == [RiskLevel.LOW, RiskLevel.MODERATE]
    assert frames.wind[0] == [10.0, 30.0]


def test_frames_use_checkpoint_hour_alignment(name):
    # Frame h is at 12:20 + h. Wind: nearest hour (12:00 for h=0). Rain: next full hour (13:00).
    def conditions(cell, hour):
        rain = 0.3 if hour == datetime(2026, 11, 25, 13, tzinfo=UTC) else 0.0
        wind = 50.0 if hour == datetime(2026, 11, 25, 12, tzinfo=UTC) else 5.0
        return HourValues(wind, None, rain, 0.0, 0.0)

    frames = builder(conditions, name=name)[0].build(CELLS[:1], START, load_lb=1)
    assert frames.wind[0] == [50.0] and frames.rain[0] == [0.3]
    assert frames.risk[0] == [RiskLevel.SEVERE]
    assert frames.risk[1] == [RiskLevel.LOW]  # 13:20: wind from 13:00, rain from 14:00


def test_frames_reuse_classify_with_the_entered_load(name):
    windy = builder(lambda c, h: HourValues(40.0, 0, 0, 0, 0), name=name)[0]
    assert windy.build(CELLS[:1], START, load_lb=40_000).risk[0] == [RiskLevel.HIGH]
    assert windy.build(CELLS[:1], START, load_lb=40_001).risk[0] == [RiskLevel.SEVERE]


def test_missing_forecast_is_null_not_low(name):
    frames = builder(name=name, missing=[CELLS[1]])[0].build(CELLS, START, load_lb=1)
    assert frames.risk[0] == [RiskLevel.LOW, None]
    assert frames.wind[0][1] is None and frames.rain[0][1] is None and frames.snow[0][1] is None


def test_fetches_one_window_covering_all_49_hours(name):
    built, weather = builder(name=name)
    built.build(CELLS, START, load_lb=1)
    assert sorted(set(weather.requested_cells), key=lambda c: c.lat) == CELLS
    assert len(weather.requested_cells) == 2  # one provider call for both cells


def test_gust_source_scores_gusts(name):
    frames = builder(lambda c, h: HourValues(5.0, 60.0, 0, 0, 0), name=name, wind_source="gust")[
        0
    ].build(CELLS[:1], START, load_lb=1)
    assert frames.risk[0] == [RiskLevel.NO_TRAVEL]
    assert frames.wind[0] == [60.0]  # the wind layer shows the scored wind


def test_start_is_hour_zero(name):
    frames = builder(name=name)[0].build(CELLS[:1], START, load_lb=1)
    assert frames.times[0] == START and frames.times[48] == START + timedelta(hours=48)
