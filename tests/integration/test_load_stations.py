"""User Story 1: a reviewer loads station data offline with one command."""

from decimal import Decimal
from pathlib import Path

import pytest
from django.conf import settings
from django.core.management import call_command

from stations.enums import GeoSource
from stations.models import FuelPrice, FuelStation

pytestmark = pytest.mark.django_db

CANADIAN_CODES = {"AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT"}
SHIPPED_FIXTURE = Path(settings.BASE_DIR) / "stations" / "fixtures" / "stations.json"


def assert_shipped_shape():
    stations = FuelStation.objects.all()
    assert not stations.filter(state__in=CANADIAN_CODES).exists()
    for station in stations:
        assert station.lat is not None and station.lng is not None
        assert station.geo_source == GeoSource.CITY_CENTROID
        assert station.match_score is None
    assert not FuelPrice.objects.filter(station__isnull=True).exists()


def test_sample_fixture_loads_offline(fixtures_dir):
    call_command("loaddata", fixtures_dir / "stations_sample.json", verbosity=0)

    assert FuelStation.objects.count() == 3
    assert FuelPrice.objects.count() == 4
    assert_shipped_shape()


def test_sample_fixture_keeps_eight_decimal_prices_exact(fixtures_dir):
    call_command("loaddata", fixtures_dir / "stations_sample.json", verbosity=0)

    assert FuelStation.objects.get(pk=7).best_price == Decimal("3.00733333")
    assert FuelPrice.objects.filter(price=Decimal("3.00733333")).count() == 1


@pytest.mark.skipif(not SHIPPED_FIXTURE.exists(), reason="stations.json is produced by T031")
def test_shipped_fixture_loads_by_name():
    call_command("loaddata", "stations", verbosity=0)

    assert FuelStation.objects.count() > 6000
    assert_shipped_shape()
