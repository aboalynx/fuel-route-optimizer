"""Load the place and station indexes when a server process starts, so no request pays for it.

Called from config/wsgi.py and config/asgi.py, which only serving processes import (runserver,
gunicorn, uvicorn), never from AppConfig.ready(): migrate, loaddata and the tests stay unaffected.
Missing data is logged, not raised: the server still starts and requests report the error as usual.
"""

import logging

from api.services.places import get_place_index
from planner.locations import PlaceDataMissing
from planner.station_index import StationDataMissing
from stations.services.index_loader import get_station_index

logger = logging.getLogger(__name__)


def warm_indexes() -> None:
    for load in (get_place_index, get_station_index):
        try:
            load()
        except (PlaceDataMissing, StationDataMissing) as error:
            logger.warning("index not preloaded, will load on first use: %s", error)
