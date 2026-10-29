import ast
import inspect

import stations.enums
from stations.enums import GeoSource


def test_geo_source_values_are_the_stored_strings():
    assert GeoSource.CITY_CENTROID == "city_centroid"
    assert GeoSource.OSM == "osm"


def test_geo_source_choices_feed_the_model_field():
    assert GeoSource.choices() == [
        ("city_centroid", "City centroid"),
        ("manual", "Manual override"),
        ("osm", "OpenStreetMap"),
    ]
    assert GeoSource.MANUAL == "manual"


def test_enums_module_does_not_import_django():
    tree = ast.parse(inspect.getsource(stations.enums))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)

    assert not any(name.split(".")[0] == "django" for name in modules)


def test_match_via_values():
    from stations.enums import MatchVia

    assert [m.value for m in MatchVia] == ["primary", "alternate", "compact"]


def test_unmatched_reason_values():
    from stations.enums import UnmatchedReason

    assert UnmatchedReason.NOT_FOUND == "not found"
    assert UnmatchedReason.REJECTED == "rejected match"
