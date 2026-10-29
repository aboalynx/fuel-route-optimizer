"""T013: the station-index loader service (Django)."""

import logging
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.db import OperationalError

from planner.station_index import StationDataMissing
from stations.services import index_loader
from stations.services.index_loader import get_station_index

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def fresh_index():
    get_station_index.cache_clear()
    yield
    get_station_index.cache_clear()


def load_sample(fixtures_dir):
    call_command("loaddata", fixtures_dir / "stations_sample.json", verbosity=0)


def test_loads_the_stations_with_exact_prices(fixtures_dir):
    load_sample(fixtures_dir)

    index = get_station_index()

    assert index.opis_ids.tolist() == [7, 9, 20]
    assert index.info[0].best_price == Decimal("3.00733333")


def test_built_once_then_no_queries(fixtures_dir, django_assert_num_queries):
    load_sample(fixtures_dir)
    first = get_station_index()

    with django_assert_num_queries(0):
        second = get_station_index()

    assert second is first
    assert get_station_index.cache_info().misses == 1


def test_empty_database_raises_and_is_not_cached(fixtures_dir):
    with pytest.raises(StationDataMissing, match="python manage.py loaddata stations"):
        get_station_index()

    load_sample(fixtures_dir)

    assert len(get_station_index().opis_ids) == 3


def test_database_error_is_logged_and_reported(monkeypatch, caplog):
    def broken():
        raise OperationalError("no such table: stations_fuelstation")

    monkeypatch.setattr(index_loader, "_read_rows", broken)

    with (
        caplog.at_level(logging.WARNING, logger="stations.services.index_loader"),
        pytest.raises(StationDataMissing) as exc,
    ):
        get_station_index()

    assert "no such table: stations_fuelstation" in str(exc.value)
    assert any("no such table: stations_fuelstation" in r.getMessage() for r in caplog.records)
