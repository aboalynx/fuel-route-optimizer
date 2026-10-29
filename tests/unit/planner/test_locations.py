"""T005: resolving "City, ST" and coordinates against the committed place file (pure, no Django)."""

import ast
import csv
import gzip
import inspect

import pytest

import planner.locations
from planner.locations import (
    LocationNotFound,
    LocationOutsideUS,
    PlaceDataMissing,
    load_place_index,
    resolve_name,
    resolve_point,
)

HEADER = ["normalised_name", "display_name", "state", "lat", "lng", "population"]
ROWS = [
    ["chicago", "Chicago", "IL", "41.85003", "-87.65005", "2664452"],
    ["new york city", "New York City", "NY", "40.71427", "-74.00597", "8804190"],
    ["south coffeyville", "South Coffeyville", "OK", "36.99452", "-95.62026", "772"],
    ["dallas", "Dallas", "TX", "32.78306", "-96.80667", "1300092"],
    ["de forest", "De Forest", "WI", "43.24778", "-89.34373", "8936"],
]


def write_places(path, rows):
    with gzip.open(path, "wt", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(HEADER)
        writer.writerows(rows)
    return path


@pytest.fixture
def index(tmp_path):
    return load_place_index(write_places(tmp_path / "places.csv.gz", ROWS))


@pytest.mark.parametrize("text", ["Dallas, TX", "dallas, tx", "  Dallas ,  TX "])
def test_city_and_state_resolve_case_insensitively(index, text):
    location = resolve_name(index, text)
    assert (location.lat, location.lng) == (32.78306, -96.80667)
    assert location.place_name == "Dallas, TX"
    assert location.query == text


@pytest.mark.parametrize(
    ("text", "name"),
    [("DeForest, WI", "De Forest, WI"), ("S Coffeyville, OK", "South Coffeyville, OK")],
)
def test_compact_and_direction_spellings_resolve(index, text, name):
    assert resolve_name(index, text).place_name == name


@pytest.mark.parametrize("text", ["Dallas, Texas", "Dallas", "Dallas, T"])
def test_state_must_be_a_two_letter_code(index, text):
    with pytest.raises(LocationNotFound, match="2-letter state code") as caught:
        resolve_name(index, text)
    assert caught.value.query == text
    assert caught.value.field is None


@pytest.mark.parametrize("text", ["Toronto, ON", "San Juan, PR", "Calgary, ab"])
def test_non_us_states_and_territories_are_outside_the_us(index, text):
    with pytest.raises(
        LocationOutsideUS, match="only the 50 states and DC are supported"
    ) as caught:
        resolve_name(index, text)
    assert caught.value.field is None


def test_common_name_alias_resolves(index):
    # GeoNames calls it "New York City"; "New York, NY" is how people write it.
    assert resolve_name(index, "New York, NY").place_name == "New York City, NY"


def test_unknown_state_code(index):
    with pytest.raises(LocationNotFound, match="unknown state code 'XX'"):
        resolve_name(index, "Springfield, XX")


def test_unknown_city_names_the_input(index):
    with pytest.raises(LocationNotFound, match="Atlantis, TX"):
        resolve_name(index, "Atlantis, TX")


def test_point_near_a_place_is_inside_and_echoed(index):
    location = resolve_point(index, 32.78, -96.80)
    assert (location.lat, location.lng) == (32.78, -96.80)
    assert location.query == "32.78,-96.8"
    assert location.place_name == "Dallas, TX"


def test_point_more_than_25_miles_from_every_place_is_outside(index):
    with pytest.raises(LocationOutsideUS) as caught:
        resolve_point(index, 33.23, -96.80)  # ~31 mi north of Dallas, the only TX place
    assert caught.value.query == "33.23,-96.8"
    with pytest.raises(LocationOutsideUS):
        resolve_point(index, 19.43, -99.13)  # Mexico City


MISSING_MESSAGE = (
    "place data missing: {path} (restore it from git or rebuild with "
    "python manage.py build_station_data)"
)


@pytest.mark.parametrize("kind", ["missing", "empty", "not gzip", "header only"])
def test_unusable_place_file_raises_place_data_missing(tmp_path, kind):
    path = tmp_path / "places.csv.gz"
    if kind == "empty":
        path.write_bytes(b"")
    elif kind == "not gzip":
        path.write_text("normalised_name,display_name\n")
    elif kind == "header only":
        write_places(path, [])
    with pytest.raises(PlaceDataMissing) as caught:
        load_place_index(path, label="data/places/us_places.csv.gz")
    assert str(caught.value) == MISSING_MESSAGE.format(path="data/places/us_places.csv.gz")


def test_label_defaults_to_the_path(tmp_path):
    path = tmp_path / "nope.csv.gz"
    with pytest.raises(PlaceDataMissing, match=str(path)):
        load_place_index(path)


def test_locations_module_does_not_import_django():
    tree = ast.parse(inspect.getsource(planner.locations))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)

    assert not any(name.split(".")[0] == "django" for name in modules)
