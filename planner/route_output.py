"""Map output for a planned route: a thinned line, points at a mile marker, GeoJSON (pure).

Stops, distances and costs always come from the full route; only the drawn line is thinned.
"""

import math
from collections.abc import Sequence

import numpy as np

from planner.geometry import cumulative_miles
from routing.base import LatLng, Route

MAX_LINE_POINTS = 5000


def thin_line(points: Sequence[LatLng], max_points: int = MAX_LINE_POINTS) -> list[LatLng]:
    """Every ceil(n / max_points)-th point plus the last one: at most max_points + 1 points."""
    points = list(points)
    if len(points) <= max_points:
        return points
    thinned = points[:: math.ceil(len(points) / max_points)]
    if thinned[-1] != points[-1]:
        thinned.append(points[-1])
    return thinned


def point_at_mile(route: Route, mile: float) -> LatLng:
    """The point at a mile marker (miles in the provider's scale, like the corridor search)."""
    coords = np.array([(p.lat, p.lng) for p in route.points], dtype=float)
    cumulative = cumulative_miles(coords)
    geometry_miles = cumulative[-1]
    if geometry_miles <= 0:
        return route.points[0]
    target = (
        min(max(float(mile), 0.0), route.distance_miles) * geometry_miles / route.distance_miles
    )
    if target <= 0:
        return route.points[0]
    if target >= geometry_miles:
        return route.points[-1]
    i = int(np.searchsorted(cumulative, target, side="right")) - 1
    t = (target - cumulative[i]) / (cumulative[i + 1] - cumulative[i])
    lat, lng = coords[i] + t * (coords[i + 1] - coords[i])
    return LatLng(float(lat), float(lng))


def route_geojson(points: Sequence[LatLng], stops: Sequence[dict]) -> dict:
    """A FeatureCollection: the route LineString, then one Point per stop ([lng, lat] order).

    Each stop dict carries lat and lng plus the properties to show on its marker.
    """
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [[p.lng, p.lat] for p in points]},
            "properties": {"kind": "route"},
        }
    ]
    for stop in stops:
        properties = {k: v for k, v in stop.items() if k not in ("lat", "lng")}
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [stop["lng"], stop["lat"]]},
                "properties": {"kind": "fuel_stop", **properties},
            }
        )
    return {"type": "FeatureCollection", "features": features}
