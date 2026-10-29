"""T009: the map line, points at a mile marker and the GeoJSON (pure, no Django)."""

import ast
import inspect

import pytest

import planner.route_output
from planner.route_output import point_at_mile, route_geojson, thin_line
from routing.base import LatLng, Route


def line(n):
    return [LatLng(30 + i * 0.001, -97.0) for i in range(n)]


@pytest.mark.parametrize(
    ("n", "max_points"), [(10, 5000), (5000, 5000), (5001, 5000), (12345, 100)]
)
def test_thin_line_bounds_and_ends(n, max_points):
    points = line(n)
    thinned = thin_line(points, max_points)
    assert len(thinned) <= max_points + 1
    assert thinned[0] == points[0]
    assert thinned[-1] == points[-1]
    if n <= max_points:
        assert thinned == points


def test_point_at_mile_ends_and_middle():
    # A 2-point route due north; the provider distance is twice the geometry length, so the
    # provider's mile 100 is halfway along the geometry.
    a, b = LatLng(30.0, -97.0), LatLng(31.0, -97.0)
    route = Route(points=(a, b), distance_miles=200.0, provider="test")
    assert point_at_mile(route, 0) == a
    assert point_at_mile(route, 200) == b
    middle = point_at_mile(route, 100)
    assert middle.lat == pytest.approx(30.5)
    assert middle.lng == pytest.approx(-97.0)


def test_point_at_mile_clamps_outside_the_route():
    a, b = LatLng(30.0, -97.0), LatLng(31.0, -97.0)
    route = Route(points=(a, b), distance_miles=69.0, provider="test")
    assert point_at_mile(route, -5) == a
    assert point_at_mile(route, 1000) == b


def test_route_geojson_shape():
    points = [LatLng(32.78, -96.8), LatLng(35.0, -92.0), LatLng(41.88, -87.63)]
    stops = [
        {
            "sequence": 1,
            "opis_id": 7,
            "name": "WOODSHED",
            "lat": 35.0,
            "lng": -92.0,
            "price_usd_per_gallon": 3.1,
            "gallons": 12.5,
            "cost_usd": 38.75,
        }
    ]
    collection = route_geojson(points, stops)
    assert collection["type"] == "FeatureCollection"
    route_feature, stop_feature = collection["features"]
    assert route_feature == {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": [[-96.8, 32.78], [-92.0, 35.0], [-87.63, 41.88]],
        },
        "properties": {"kind": "route"},
    }
    assert stop_feature["geometry"] == {"type": "Point", "coordinates": [-92.0, 35.0]}
    assert stop_feature["properties"] == {
        "kind": "fuel_stop",
        "sequence": 1,
        "opis_id": 7,
        "name": "WOODSHED",
        "price_usd_per_gallon": 3.1,
        "gallons": 12.5,
        "cost_usd": 38.75,
    }


def test_route_output_module_does_not_import_django():
    tree = ast.parse(inspect.getsource(planner.route_output))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)

    assert not any(name.split(".")[0] == "django" for name in modules)
