"""T011: the in-memory station index (pure, no Django)."""

import ast
import inspect
from decimal import Decimal

import pytest

import planner.station_index
from planner.station_index import StationDataMissing, build_station_index
from stations.enums import GeoSource

ROWS = [
    (
        20,
        32.94,
        -112.71,
        Decimal("3.899"),
        "PILOT #1243",
        "I-8",
        "Gila Bend",
        "AZ",
        "city_centroid",
    ),
    (7, 36.53, -95.22, Decimal("3.00733333"), "WOODSHED", "I-44", "Big Cabin", "OK", "manual"),
    (
        9,
        43.97,
        -90.50,
        Decimal("3.28733333"),
        "KWIK TRIP #796",
        "I-94",
        "Tomah",
        "WI",
        "city_centroid",
    ),
]


def test_index_is_sorted_by_opis_id():
    index = build_station_index(ROWS)

    assert index.opis_ids.tolist() == [7, 9, 20]
    assert index.lat.tolist() == [36.53, 43.97, 32.94]
    assert index.tree.n == 3


def test_index_keeps_exact_price_and_details():
    info = build_station_index(ROWS).info[0]

    assert info.opis_id == 7
    assert info.best_price == Decimal("3.00733333")
    assert (info.name, info.address, info.city, info.state) == (
        "WOODSHED",
        "I-44",
        "Big Cabin",
        "OK",
    )
    assert info.geo_source is GeoSource.MANUAL


def test_no_rows_raises_station_data_missing():
    with pytest.raises(StationDataMissing) as exc:
        build_station_index([])

    assert str(exc.value) == "station data not loaded: run python manage.py loaddata stations"


def test_station_index_module_does_not_import_django():
    tree = ast.parse(inspect.getsource(planner.station_index))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)

    assert not any(name.split(".")[0] == "django" for name in modules)
