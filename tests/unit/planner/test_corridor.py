"""T012: corridor search - gather on the densified route, then measure exactly (pure)."""

import logging
import math
from decimal import Decimal

import pytest

from planner.corridor import find_candidates
from planner.geometry import haversine_miles
from routing.base import LatLng, Route
from tests.unit.planner.conftest import MILES_PER_DEGREE, arc_route, offset, straight_route

BASE = (35.0, -100.0)


def route_of(points, distance_miles=None):
    if distance_miles is None:
        distance_miles = sum(
            haversine_miles(*a, *b) for a, b in zip(points[:-1], points[1:], strict=True)
        )
    return Route(tuple(LatLng(lat, lng) for lat, lng in points), distance_miles, "test")


def north_route(miles, start=BASE, step=1.0):
    return route_of(straight_route(*start, 0, miles, step))  # due north: exact distances


def by_id(candidates):
    return {c.opis_id: c for c in candidates}


# --- mile markers and the radius -----------------------------------------------------------


def test_mile_markers_on_a_straight_line(make_index):
    index = make_index([(1, *offset(*BASE, 50, 2), 3.1), (2, *offset(*BASE, 123.4, -5), 3.2)])

    found = by_id(find_candidates(north_route(200), index, 10))

    assert found[1].mile_marker == pytest.approx(50, abs=0.05)
    assert found[2].mile_marker == pytest.approx(123.4, abs=0.05)


def test_radius_boundary_is_sharp(make_index):
    lat_mid = BASE[0] + 50 / MILES_PER_DEGREE
    index = make_index(
        [
            (1, *offset(lat_mid, BASE[1], 0, 9.99), 3.1),
            (2, *offset(lat_mid, BASE[1], 0, 10.01), 3.2),
        ]
    )

    found = by_id(find_candidates(north_route(100), index, 10))

    assert 1 in found and found[1].off_route_miles == pytest.approx(9.99, abs=0.01)
    assert 2 not in found


def test_station_on_the_route_reads_zero(make_index):
    index = make_index([(1, *offset(*BASE, 30.5, 0), 3.1)])

    candidate = find_candidates(north_route(100), index, 10)[0]

    assert candidate.off_route_miles == pytest.approx(0, abs=0.01)
    assert candidate.mile_marker == pytest.approx(30.5, abs=0.05)


def test_sparse_segment_still_finds_a_midpoint_station(make_index):
    start, end = BASE, offset(*BASE, 100, 0)
    index = make_index([(1, *offset(*BASE, 50, 3), 3.1)])

    found = find_candidates(route_of([start, end]), index, 10)

    assert [c.opis_id for c in found] == [1]
    assert found[0].mile_marker == pytest.approx(50, abs=0.05)


@pytest.mark.parametrize("latitude", [31.0, 48.0], ids=["texas", "montana"])
def test_radius_is_in_miles_at_any_latitude(make_index, latitude):
    start = (latitude, -100.0)
    lat_mid = latitude + 50 / MILES_PER_DEGREE
    index = make_index([(1, *offset(lat_mid, -100.0, 0, 9.5), 3.1)])

    found = find_candidates(north_route(100, start=start), index, 10)

    assert [c.opis_id for c in found] == [1]


def test_curve_has_no_corner_cutting(make_index):
    center = (40.0, -100.0)
    points = arc_route(*center, radius_miles=1, start_deg=0, end_deg=180, n_points=181)
    station = offset(*center, math.cos(math.radians(90.5)), math.sin(math.radians(90.5)))
    index = make_index([(1, *station, 3.1)])

    candidate = find_candidates(route_of(points, distance_miles=math.pi), index, 10)[0]

    assert candidate.off_route_miles == pytest.approx(0, abs=0.01)
    assert candidate.mile_marker == pytest.approx(math.radians(90.5), abs=0.05)


# --- rescaling ------------------------------------------------------------------------------


def test_mile_markers_use_the_provider_distance(make_index, caplog):
    points = straight_route(*BASE, 0, 100, 1.0)
    index = make_index([(1, *points[-1], 3.1)])

    with caplog.at_level(logging.WARNING, logger="planner.corridor"):
        candidate = find_candidates(route_of(points, distance_miles=102), index, 10)[0]

    assert candidate.mile_marker == pytest.approx(102, abs=0.05)
    assert caplog.records == []  # 2% is within 0.95-1.05


def test_large_distance_mismatch_logs_a_warning(make_index, caplog):
    points = straight_route(*BASE, 0, 100, 1.0)
    index = make_index([(1, *offset(*BASE, 50, 1), 3.1)])

    with caplog.at_level(logging.WARNING, logger="planner.corridor"):
        found = find_candidates(route_of(points, distance_miles=110), index, 10)

    assert found
    assert any("geometry" in r.getMessage() for r in caplog.records)


# --- loops and ordering ---------------------------------------------------------------------


def u_turn_route():
    """North 20 mi, east 2 mi, south 20 mi."""
    up = straight_route(*BASE, 0, 20, 1.0)
    top_east = offset(*up[-1], 0, 2)
    down = straight_route(*top_east, 180, 20, 1.0)
    return route_of(up + down)


def leg_lngs_at(route, mile):
    lat = BASE[0] + mile / MILES_PER_DEGREE
    return lat, route.points[0].lng, route.points[-1].lng


def test_loop_lists_a_station_once_at_the_nearer_pass(make_index):
    route = u_turn_route()
    lat, west, east = leg_lngs_at(route, 10)
    near_second = (lat, west + 0.75 * (east - west))
    index = make_index([(1, *near_second, 3.1)])

    found = find_candidates(route, index, 10)

    assert [c.opis_id for c in found] == [1]
    assert found[0].mile_marker == pytest.approx(32, abs=0.1)  # 20 up + 2 across + 10 down


def test_loop_tie_takes_the_earlier_mile(make_index):
    route = u_turn_route()
    lat, west, east = leg_lngs_at(route, 10)
    index = make_index([(1, lat, (west + east) / 2, 3.1)])

    found = find_candidates(route, index, 10)

    assert [c.opis_id for c in found] == [1]
    assert found[0].mile_marker == pytest.approx(10, abs=0.05)


def test_order_is_mile_then_opis_id_and_stable(make_index):
    index = make_index(
        [
            (7, *offset(*BASE, 40, 3), 3.1),
            (3, *offset(*BASE, 40, -3), 3.2),
            (5, *offset(*BASE, 20, 1), 3.3),
        ]
    )
    route = north_route(100)

    first = find_candidates(route, index, 10)

    assert [c.opis_id for c in first] == [5, 3, 7]
    assert find_candidates(route, index, 10) == first


# --- fields and limits ---------------------------------------------------------------------


def test_candidate_carries_the_exact_price(make_index):
    index = make_index([(1, *offset(*BASE, 10, 1), "3.00733333")])

    assert find_candidates(north_route(50), index, 10)[0].price == Decimal("3.00733333")


def test_no_station_nearby_gives_an_empty_list(make_index):
    index = make_index([(1, *offset(*BASE, 10, 50), 3.1)])

    assert find_candidates(north_route(50), index, 10) == []


@pytest.mark.parametrize("radius", [0.5, 26])
def test_radius_out_of_range(make_index, radius):
    index = make_index([(1, *offset(*BASE, 10, 1), 3.1)])

    with pytest.raises(ValueError, match="1 to 25"):
        find_candidates(north_route(50), index, radius)
