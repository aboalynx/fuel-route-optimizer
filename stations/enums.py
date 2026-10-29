"""Fixed value sets for the stations app.

Pure Python (no Django import), so the pipeline modules can use them too.
Model fields take their choices from these enums via ``choices()``.
"""

from enum import StrEnum


class GeoSource(StrEnum):
    """Where a station's coordinates come from."""

    CITY_CENTROID = "city_centroid"
    OSM = "osm"

    @property
    def label(self) -> str:
        return _GEO_SOURCE_LABELS[self]

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        return [(member.value, member.label) for member in cls]


_GEO_SOURCE_LABELS = {
    GeoSource.CITY_CENTROID: "City centroid",
    GeoSource.OSM: "OpenStreetMap",
}


class MatchVia(StrEnum):
    """Which gazetteer name located a station: the main name, or an alternate as a fallback."""

    PRIMARY = "primary"
    ALTERNATE = "alternate"
