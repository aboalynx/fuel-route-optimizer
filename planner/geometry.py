"""Distances and route geometry in miles (pure numpy, no Django).

Coordinates are (lat, lng) in degrees. Distances are great-circle miles on a sphere of radius
3958.8 mi, except project_onto_segment, which works in a local flat frame around one point
(accurate to well under 0.01 mile over the short segments it is used on).
"""

import math

import numpy as np

EARTH_RADIUS_MILES = 3958.8
MILES_PER_DEGREE = math.pi * EARTH_RADIUS_MILES / 180


def haversine_miles(lat1, lng1, lat2, lng2):
    """Great-circle distance in miles; works on floats and numpy arrays."""
    lat1, lng1, lat2, lng2 = map(np.radians, (lat1, lng1, lat2, lng2))
    a = (
        np.sin((lat2 - lat1) / 2) ** 2
        + np.cos(lat1) * np.cos(lat2) * np.sin((lng2 - lng1) / 2) ** 2
    )
    distance = 2 * EARTH_RADIUS_MILES * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))
    return float(distance) if np.ndim(distance) == 0 else distance


def segment_miles(points: np.ndarray) -> np.ndarray:
    """Length of each segment of an (n, 2) array of (lat, lng)."""
    return haversine_miles(points[:-1, 0], points[:-1, 1], points[1:, 0], points[1:, 1])


def densify(points: np.ndarray, spacing: float) -> np.ndarray:
    """Keep every original point and insert linearly interpolated points so that no segment is
    longer than `spacing`. The result is the same polyline with extra vertices, so curves are
    never cut."""
    points = np.asarray(points, dtype=float)
    pieces = [points[:1]]
    for a, b in zip(points[:-1], points[1:], strict=True):
        length = haversine_miles(*a, *b)
        parts = max(1, math.ceil(length / spacing))
        while True:
            t = np.linspace(0.0, 1.0, parts + 1)[1:, None]
            inserted = a + (b - a) * t
            inserted[-1] = b  # keep the original point bit for bit
            chain = np.vstack([a, inserted])
            if segment_miles(chain).max(initial=0.0) <= spacing + 1e-9:
                break
            parts += 1  # equal lat/lng steps are not always equal miles
        pieces.append(inserted)
    return np.vstack(pieces)


def cumulative_miles(points: np.ndarray) -> np.ndarray:
    """Distance along the polyline at each point, starting at 0."""
    return np.concatenate([[0.0], np.cumsum(segment_miles(np.asarray(points, dtype=float)))])


def to_unit_vectors(lat, lng) -> np.ndarray:
    """(n, 3) unit vectors; Euclidean distance between them is the chord on the unit sphere."""
    lat, lng = np.radians(np.asarray(lat, dtype=float)), np.radians(np.asarray(lng, dtype=float))
    return np.column_stack([np.cos(lat) * np.cos(lng), np.cos(lat) * np.sin(lng), np.sin(lat)])


def chord_for_miles(miles: float) -> float:
    return 2 * math.sin(miles / (2 * EARTH_RADIUS_MILES))


def arc_miles(chord: float) -> float:
    return 2 * EARTH_RADIUS_MILES * math.asin(min(1.0, chord / 2))


def project_onto_segment(
    lat: float, lng: float, a_lat: float, a_lng: float, b_lat: float, b_lng: float
) -> tuple[float, float]:
    """Distance in miles from a point to segment A-B, and the fraction t (0..1) of the closest
    point along A-B, in a local equirectangular frame centred on the point."""
    scale_x = math.cos(math.radians(lat)) * MILES_PER_DEGREE
    ax, ay = (a_lng - lng) * scale_x, (a_lat - lat) * MILES_PER_DEGREE
    bx, by = (b_lng - lng) * scale_x, (b_lat - lat) * MILES_PER_DEGREE
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    t = 0.0 if length_sq == 0 else min(1.0, max(0.0, -(ax * dx + ay * dy) / length_sq))
    return math.hypot(ax + t * dx, ay + t * dy), t
