"""Synthetic routes and stations for the corridor tests (no network, no DB)."""

import math
from decimal import Decimal

import pytest

EARTH_RADIUS_MILES = 3958.8
MILES_PER_DEGREE = math.pi * EARTH_RADIUS_MILES / 180


def offset(lat: float, lng: float, north_miles: float, east_miles: float) -> tuple[float, float]:
    """Move a point by small distances in a local equirectangular frame."""
    new_lat = lat + north_miles / MILES_PER_DEGREE
    new_lng = lng + east_miles / (MILES_PER_DEGREE * math.cos(math.radians(lat)))
    return new_lat, new_lng


def straight_route(
    lat: float, lng: float, bearing_deg: float, miles: float, step_miles: float
) -> list[tuple[float, float]]:
    """Points every step_miles along a straight line from (lat, lng)."""
    steps = max(1, round(miles / step_miles))
    bearing = math.radians(bearing_deg)
    return [
        offset(lat, lng, d * math.cos(bearing), d * math.sin(bearing))
        for d in (miles * i / steps for i in range(steps + 1))
    ]


def arc_route(
    center_lat: float,
    center_lng: float,
    radius_miles: float,
    start_deg: float,
    end_deg: float,
    n_points: int,
) -> list[tuple[float, float]]:
    """Points on a circular arc around a centre, angles measured clockwise from north."""
    angles = [start_deg + (end_deg - start_deg) * i / (n_points - 1) for i in range(n_points)]
    return [
        offset(
            center_lat,
            center_lng,
            radius_miles * math.cos(math.radians(a)),
            radius_miles * math.sin(math.radians(a)),
        )
        for a in angles
    ]


@pytest.fixture
def make_index():
    """Build a StationIndex from (opis_id, lat, lng, price) tuples."""
    from planner.station_index import build_station_index

    from stations.enums import GeoSource

    def _make(stations):
        rows = [
            (
                opis_id,
                lat,
                lng,
                Decimal(str(price)),
                f"STATION {opis_id}",
                "",
                "",
                "",
                GeoSource.CITY_CENTROID,
            )
            for opis_id, lat, lng, price in stations
        ]
        return build_station_index(rows)

    return _make
