"""Resolve "City, ST" and coordinates against the committed place file (pure, no Django).

The place file (data/places/us_places.csv.gz) is written by build_station_data with the same name
rules used to locate stations, so every city a station was matched to also resolves here. No
geocoding call is made. Coordinates count as inside the USA when the nearest place is within
25 miles.
"""

import csv
import gzip
import re
from dataclasses import dataclass
from pathlib import Path

from scipy.spatial import cKDTree

from planner.geometry import chord_for_miles, to_unit_vectors
from stations.pipeline.geonames import compact_place_name, normalise_place_name

MAX_PLACE_DISTANCE_MILES = 25
STATE_CODE = re.compile(r"^[A-Za-z]{2}$")
# Canadian provinces/territories and US territories: real places, but outside the station data.
NON_US_CODES = frozenset(
    [
        "AB",
        "BC",
        "MB",
        "NB",
        "NL",
        "NS",
        "NT",
        "NU",
        "ON",
        "PE",
        "QC",
        "SK",
        "YT",
        "PR",
        "VI",
        "GU",
        "AS",
        "MP",
    ]
)
TWO_LETTER_HINT = "use a 2-letter state code, e.g. 'Dallas, TX'"
# Names people use that GeoNames lists differently (normalised name, state) -> place file name.
ALIASES = {("new york", "NY"): "new york city"}


class PlaceDataMissing(Exception):
    def __init__(self, label: str):
        self.label = label
        super().__init__(
            f"place data missing: {label} (restore it from git or rebuild with "
            "python manage.py build_station_data)"
        )


class LocationError(Exception):
    """Base for location errors. `field` ("start"/"finish") is set by the caller."""

    def __init__(self, query: str, message: str, field: str | None = None):
        self.query = query
        self.message = message
        self.field = field
        super().__init__(message)


class LocationNotFound(LocationError):
    pass


class LocationOutsideUS(LocationError):
    pass


@dataclass(frozen=True)
class Place:
    normalised_name: str
    display_name: str
    state: str
    lat: float
    lng: float
    population: int

    @property
    def label(self) -> str:
        return f"{self.display_name}, {self.state}"


@dataclass(frozen=True, eq=False)
class PlaceIndex:
    by_name: dict[tuple[str, str], Place]
    by_compact: dict[tuple[str, str], Place]
    states: frozenset[str]
    places: tuple[Place, ...]  # same order as the tree
    tree: cKDTree


@dataclass(frozen=True)
class ResolvedLocation:
    query: str
    lat: float
    lng: float
    place_name: str | None  # the matched place, or the nearest one for coordinates


def load_place_index(path: Path, label: str | None = None) -> PlaceIndex:
    """Read the place file; a missing, unreadable or empty file raises PlaceDataMissing."""
    label = label or str(path)
    try:
        with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
            places = tuple(
                Place(
                    normalised_name=row["normalised_name"],
                    display_name=row["display_name"],
                    state=row["state"],
                    lat=float(row["lat"]),
                    lng=float(row["lng"]),
                    population=int(row["population"]),
                )
                for row in csv.DictReader(f)
            )
    except (OSError, EOFError, csv.Error, KeyError, ValueError, TypeError) as error:
        raise PlaceDataMissing(label) from error
    if not places:
        raise PlaceDataMissing(label)

    by_compact: dict[tuple[str, str], Place] = {}
    for place in places:  # the file is sorted by (state, name): the first one wins
        by_compact.setdefault((compact_place_name(place.normalised_name), place.state), place)
    return PlaceIndex(
        by_name={(p.normalised_name, p.state): p for p in places},
        by_compact=by_compact,
        states=frozenset(p.state for p in places),
        places=places,
        tree=cKDTree(to_unit_vectors([p.lat for p in places], [p.lng for p in places])),
    )


def resolve_name(index: PlaceIndex, text: str) -> ResolvedLocation:
    city, _, state = text.rpartition(",")
    city, state = city.strip(), state.strip()
    if not city or not STATE_CODE.match(state):
        raise LocationNotFound(text, f"'{text}': {TWO_LETTER_HINT}")
    state = state.upper()
    if state in NON_US_CODES:
        raise LocationOutsideUS(text, f"'{text}': only the 50 states and DC are supported")
    if state not in index.states:
        raise LocationNotFound(text, f"'{text}': unknown state code '{state}'")

    name = normalise_place_name(city)
    name = ALIASES.get((name, state), name)
    place = index.by_name.get((name, state)) or index.by_compact.get(
        (compact_place_name(name), state)
    )
    if place is None:
        raise LocationNotFound(text, f"'{text}': unknown place")
    return ResolvedLocation(query=text, lat=place.lat, lng=place.lng, place_name=place.label)


def resolve_point(index: PlaceIndex, lat: float, lng: float) -> ResolvedLocation:
    query = f"{lat},{lng}"
    chord, i = index.tree.query(
        to_unit_vectors([lat], [lng])[0],
        distance_upper_bound=chord_for_miles(MAX_PLACE_DISTANCE_MILES),
    )
    if i == len(index.places):  # nothing within the bound
        raise LocationOutsideUS(
            query,
            f"({query}) is more than {MAX_PLACE_DISTANCE_MILES} miles from any US place",
        )
    return ResolvedLocation(query=query, lat=lat, lng=lng, place_name=index.places[i].label)
