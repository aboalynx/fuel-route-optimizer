from decimal import Decimal

import pytest

from stations.enums import GeoSource
from stations.models import FuelPrice, FuelStation

pytestmark = pytest.mark.django_db


def make_station(opis_id=7, price="3.00733333"):
    return FuelStation.objects.create(
        opis_id=opis_id,
        name="WOODSHED OF BIG CABIN",
        address="I-44, EXIT 283 & US-69",
        city="Big Cabin",
        state="OK",
        lat=36.53,
        lng=-95.22,
        geo_source=GeoSource.CITY_CENTROID,
        best_price=Decimal(price),
    )


def test_price_with_eight_decimals_round_trips_exactly():
    station = make_station()
    FuelPrice.objects.create(
        station=station, rack_id=307, raw_name="WOODSHED OF BIG CABIN", price=Decimal("3.00733333")
    )

    stored_station = FuelStation.objects.get(pk=7)
    stored_price = FuelPrice.objects.get(station=stored_station)

    assert stored_station.best_price == Decimal("3.00733333")
    assert stored_price.price == Decimal("3.00733333")


def test_opis_id_is_the_primary_key():
    station = make_station(opis_id=20)

    assert station.pk == 20
    assert FuelStation.objects.get(pk=20).opis_id == 20


def test_explicit_price_id_is_kept():
    station = make_station()
    FuelPrice.objects.create(id=42, station=station, rack_id=1, raw_name="X", price=Decimal("3.1"))

    assert FuelPrice.objects.get().id == 42


def test_deleting_a_station_deletes_its_prices():
    station = make_station()
    FuelPrice.objects.create(station=station, rack_id=1, raw_name="X", price=Decimal("3.1"))
    FuelPrice.objects.create(station=station, rack_id=2, raw_name="X", price=Decimal("3.2"))

    station.delete()

    assert FuelPrice.objects.count() == 0


def test_match_score_is_optional():
    assert make_station().match_score is None
