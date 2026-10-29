"""Corridor search: the stations within a radius of a route, with exact mile markers (pure).

1. Densify the route: keep every point, insert points so no segment exceeds s = min(1, r/2).
2. Gather candidates with a KD-tree ball query on the densified points (radius r + s/2), so no
   station within r is missed.
3. Measure each candidate exactly: project it onto the densified segments next to its nearest
   point (all nearest points on ties), keep the closest projection, earliest mile on ties.
4. Include it if and only if its exact off-route distance is <= r.

Mile markers are rescaled to the provider's distance. See docs/algorithms/route-corridor-search.md.
"""

import logging
import math
from dataclasses import dataclass
from decimal import Decimal

import numpy as np
from scipy.spatial import cKDTree

from planner.geometry import (
    chord_for_miles,
    cumulative_miles,
    densify,
    project_onto_segment,
    to_unit_vectors,
)
from planner.station_index import StationIndex
from routing.base import Route

logger = logging.getLogger(__name__)

MIN_RADIUS_MILES = 1
MAX_RADIUS_MILES = 25
MAX_SPACING_MILES = 1.0
RESCALE_WARNING_RANGE = (0.95, 1.05)  # provider distance / geometry length
TIE_MILES = 1e-9


@dataclass(frozen=True)
class Candidate:
    opis_id: int
    mile_marker: float
    off_route_miles: float
    price: Decimal  # the station's exact best price


def find_candidates(route: Route, index: StationIndex, corridor_miles: float) -> list[Candidate]:
    if not MIN_RADIUS_MILES <= corridor_miles <= MAX_RADIUS_MILES:
        raise ValueError(
            f"corridor radius must be {MIN_RADIUS_MILES} to {MAX_RADIUS_MILES} miles, "
            f"got {corridor_miles}"
        )
    radius = float(corridor_miles)
    spacing = min(MAX_SPACING_MILES, radius / 2)

    points = densify(np.array([(p.lat, p.lng) for p in route.points]), spacing)
    cumulative = cumulative_miles(points)
    scale = _scale(route.distance_miles, cumulative[-1])

    vectors = to_unit_vectors(points[:, 0], points[:, 1])
    hits = index.tree.query_ball_point(vectors, chord_for_miles(radius + spacing / 2))
    candidates_idx = sorted({i for row in hits for i in row})
    if not candidates_idx:
        return []

    route_tree = cKDTree(vectors)
    found = []
    for j in candidates_idx:
        off, mile = _measure(
            index.lat[j], index.lng[j], index.vectors[j], points, cumulative, route_tree
        )
        if off <= radius:
            info = index.info[j]
            found.append(Candidate(info.opis_id, mile * scale, off, info.best_price))
    return sorted(found, key=lambda c: (c.mile_marker, c.opis_id))


def _scale(provider_miles: float, geometry_miles: float) -> float:
    if geometry_miles <= 0:
        return 1.0
    scale = provider_miles / geometry_miles
    low, high = RESCALE_WARNING_RANGE
    if not low <= scale <= high:
        logger.warning(
            "provider distance %.2f mi vs route geometry %.2f mi (ratio %.3f): "
            "the geometry may be incomplete; mile markers are rescaled anyway",
            provider_miles,
            geometry_miles,
            scale,
        )
    return scale


def _measure(lat, lng, vector, points, cumulative, route_tree) -> tuple[float, float]:
    """Exact (off-route miles, mile along the geometry) for one station."""
    nearest_chord, _ = route_tree.query(vector)
    nearest = route_tree.query_ball_point(vector, nearest_chord * (1 + 1e-9) + 1e-15)
    last = len(points) - 1
    best = (math.inf, math.inf)
    for i in sorted(nearest):
        for a in (i - 1, i):  # the segments touching point i
            if 0 <= a < last:
                off, t = project_onto_segment(lat, lng, *points[a], *points[a + 1])
                mile = cumulative[a] + t * (cumulative[a + 1] - cumulative[a])
                if off < best[0] - TIE_MILES or (
                    abs(off - best[0]) <= TIE_MILES and mile < best[1]
                ):
                    best = (off, mile)
    return best
