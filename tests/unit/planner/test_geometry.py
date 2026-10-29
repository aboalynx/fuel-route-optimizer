"""T010: geometry helpers (pure, no Django)."""

import math

import numpy as np
import pytest

from planner.geometry import (
    arc_miles,
    chord_for_miles,
    cumulative_miles,
    densify,
    haversine_miles,
    project_onto_segment,
    to_unit_vectors,
)
from tests.unit.planner.conftest import offset


def test_haversine_dallas_chicago():
    assert haversine_miles(32.78, -96.80, 41.88, -87.63) == pytest.approx(804.7, abs=1)
    assert haversine_miles(32.78, -96.80, 32.78, -96.80) == 0


def segment_lengths(points):
    return haversine_miles(points[:-1, 0], points[:-1, 1], points[1:, 0], points[1:, 1])


def test_densify_keeps_every_point_and_caps_segment_length():
    original = np.array(
        [
            offset(35, -100, 0, 0),
            offset(35, -100, 0.4, 0),
            offset(35, -100, 7.3, 2.1),
            offset(35, -100, 30, 5),
        ]
    )

    dense = densify(original, spacing=1.0)

    kept = [i for i, p in enumerate(dense) if any(np.array_equal(p, q) for q in original)]
    assert [tuple(dense[i]) for i in kept] == [tuple(p) for p in original]  # every point, in order
    assert segment_lengths(dense).max() <= 1.0 + 1e-9


def test_densify_point_count_on_a_two_point_route():
    start = (35.0, -100.0)
    end = offset(*start, 100, 0)  # due north
    length = haversine_miles(*start, *end)

    dense = densify(np.array([start, end]), spacing=1.0)

    assert len(dense) == math.ceil(length / 1.0) + 1
    assert tuple(dense[0]) == start and tuple(dense[-1]) == end


def test_densify_leaves_a_fine_route_unchanged():
    route = np.array([offset(35, -100, d, 0) for d in (0, 0.3, 0.6, 0.9)])

    assert np.array_equal(densify(route, spacing=1.0), route)


def test_cumulative_miles():
    route = np.array([offset(35, -100, d, 0) for d in (0, 2, 5, 9)])

    cum = cumulative_miles(route)

    assert cum[0] == 0
    assert np.all(np.diff(cum) >= 0)
    assert cum[-1] == pytest.approx(segment_lengths(route).sum())
    assert cum[-1] == pytest.approx(9, abs=1e-6)


def test_unit_vectors_and_chords():
    vectors = to_unit_vectors(np.array([0.0, 45.0, -30.0]), np.array([0.0, -100.0, 170.0]))

    assert np.allclose(np.linalg.norm(vectors, axis=1), 1)
    for miles in (0.5, 10, 25):
        assert arc_miles(chord_for_miles(miles)) == pytest.approx(miles)


def test_project_onto_segment():
    station = offset(35, -100, 5, 0)
    a, b = offset(35, -100, 0, 0), offset(35, -100, 10, 0)

    off, t = project_onto_segment(*station, *a, *b)
    assert off == pytest.approx(0, abs=1e-9)
    assert t == pytest.approx(0.5, abs=1e-6)

    beyond = offset(35, -100, 12, 0)
    off, t = project_onto_segment(*beyond, *a, *b)
    assert t == 1
    assert off == pytest.approx(2, abs=1e-3)
