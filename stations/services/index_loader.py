"""Load the station index once per process (the only place that reads stations for searching).

Built lazily on first use, never in AppConfig.ready(). After build_station_data or loaddata,
restart the process to pick up new data. Tests reset it with get_station_index.cache_clear().
"""

import logging
from functools import lru_cache

from django.db import OperationalError, ProgrammingError

from planner.station_index import StationDataMissing, StationIndex, build_station_index
from stations.models import FuelStation

logger = logging.getLogger(__name__)

INDEX_FIELDS = (
    "opis_id",
    "lat",
    "lng",
    "best_price",
    "name",
    "address",
    "city",
    "state",
    "geo_source",
)


@lru_cache(maxsize=1)
def get_station_index() -> StationIndex:
    """The in-memory index; raises StationDataMissing (not cached) when there is no data."""
    try:
        rows = _read_rows()
    except (OperationalError, ProgrammingError) as error:
        logger.warning("station data could not be read: %s", error)
        raise StationDataMissing(str(error)) from error
    return build_station_index(rows)


def _read_rows() -> list[tuple]:
    return list(FuelStation.objects.order_by("opis_id").values_list(*INDEX_FIELDS))
