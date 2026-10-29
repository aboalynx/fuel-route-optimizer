"""Fixed value sets for the stations app.

Pure Python (no Django import), so the pipeline modules can use them too.
Model fields take their choices from these enums via ``choices()``.
"""

from enum import StrEnum


class GeoSource(StrEnum):
    """Where a station's coordinates come from."""

    CITY_CENTROID = "city_centroid"
    MANUAL = "manual"  # reviewed override, data/overrides/manual_coordinates.csv
    OSM = "osm"

    @property
    def label(self) -> str:
        return _GEO_SOURCE_LABELS[self]

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        return [(member.value, member.label) for member in cls]


_GEO_SOURCE_LABELS = {
    GeoSource.CITY_CENTROID: "City centroid",
    GeoSource.MANUAL: "Manual override",
    GeoSource.OSM: "OpenStreetMap",
}


class MatchVia(StrEnum):
    """Which lookup tier located a station, tried in this order."""

    PRIMARY = "primary"  # main name
    ALTERNATE = "alternate"  # alternate name, only if no main name matches
    COMPACT = "compact"  # spaces removed, leading direction expanded; main names only


class UnmatchedReason(StrEnum):
    """Why a station was left out of the shipped data."""

    NOT_FOUND = "not found"
    REJECTED = "rejected match"  # on the reviewed rejected-matches list
