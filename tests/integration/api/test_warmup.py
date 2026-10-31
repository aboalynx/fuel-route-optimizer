"""Preloading the indexes when a server process starts."""

import logging

import pytest
from django.core.management import call_command

from api.services.places import get_place_index
from api.services.warmup import warm_indexes
from stations.services.index_loader import get_station_index

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def fresh_indexes():
    get_place_index.cache_clear()
    get_station_index.cache_clear()
    yield
    get_place_index.cache_clear()
    get_station_index.cache_clear()


def test_loads_both_indexes(fixtures_dir):
    call_command("loaddata", fixtures_dir / "stations_sample.json", verbosity=0)

    warm_indexes()

    assert get_place_index.cache_info().currsize == 1
    assert get_station_index.cache_info().currsize == 1


def test_missing_station_data_is_logged_not_raised(caplog):
    with caplog.at_level(logging.WARNING, logger="api.services.warmup"):
        warm_indexes()

    assert get_place_index.cache_info().currsize == 1
    assert get_station_index.cache_info().currsize == 0
    assert any("will load on first use" in r.getMessage() for r in caplog.records)
