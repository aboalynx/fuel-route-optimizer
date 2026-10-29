"""In-memory station index: coordinates, a KD-tree and everything later steps need (pure).

Built once per process by stations/services/index_loader.py, so a search never queries the
database. New station data needs a restart.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

import numpy as np
from scipy.spatial import cKDTree

from planner.geometry import to_unit_vectors
from stations.enums import GeoSource

MISSING_MESSAGE = "station data not loaded: run python manage.py loaddata stations"

# (opis_id, lat, lng, best_price, name, address, city, state, geo_source)
StationRow = tuple[int, float, float, Decimal, str, str, str, str, str]


class StationDataMissing(Exception):
    def __init__(self, detail: str | None = None):
        self.detail = detail
        super().__init__(f"{MISSING_MESSAGE} ({detail})" if detail else MISSING_MESSAGE)


@dataclass(frozen=True)
class StationInfo:
    opis_id: int
    best_price: Decimal  # exact
    name: str
    address: str
    city: str
    state: str
    geo_source: GeoSource


@dataclass(frozen=True, eq=False)
class StationIndex:
    opis_ids: np.ndarray  # int64, ascending
    lat: np.ndarray
    lng: np.ndarray
    vectors: np.ndarray  # (n, 3) unit vectors
    tree: cKDTree
    info: tuple[StationInfo, ...]  # same order as opis_ids


def build_station_index(rows: Iterable[StationRow]) -> StationIndex:
    rows = sorted(rows, key=lambda row: row[0])
    if not rows:
        raise StationDataMissing()

    lat = np.array([row[1] for row in rows], dtype=float)
    lng = np.array([row[2] for row in rows], dtype=float)
    vectors = to_unit_vectors(lat, lng)
    return StationIndex(
        opis_ids=np.array([row[0] for row in rows], dtype=np.int64),
        lat=lat,
        lng=lng,
        vectors=vectors,
        tree=cKDTree(vectors),
        info=tuple(
            StationInfo(
                opis_id=opis_id,
                best_price=best_price,
                name=name,
                address=address,
                city=city,
                state=state,
                geo_source=GeoSource(geo_source),
            )
            for opis_id, _, _, best_price, name, address, city, state, geo_source in rows
        ),
    )
