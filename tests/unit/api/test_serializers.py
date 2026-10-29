"""T010: request validation for the route-plan endpoint."""

from decimal import Decimal

import pytest

from api.serializers import RoutePlanRequestSerializer


def validate(**body):
    body = {"start": "Dallas, TX", "finish": "Chicago, IL", **body}
    serializer = RoutePlanRequestSerializer(data=body)
    return serializer.is_valid(), serializer


@pytest.mark.parametrize(
    "location", ["Dallas, TX", {"lat": 32.78, "lng": -96.8}, {"lat": -90, "lng": 180}]
)
def test_locations_accept_a_name_or_coordinates(location):
    ok, serializer = validate(start=location)
    assert ok, serializer.errors


def test_coordinates_become_a_float_pair_and_names_are_trimmed():
    ok, serializer = validate(start={"lat": 32.78, "lng": -96.8}, finish="  Chicago, IL ")
    assert ok
    assert serializer.validated_data["start"] == (32.78, -96.8)
    assert serializer.validated_data["finish"] == "Chicago, IL"


@pytest.mark.parametrize(
    "location",
    [
        {"lat": 200, "lng": 0},
        {"lat": 0, "lng": -181},
        {"lat": "x", "lng": 0},
        {"lat": True, "lng": 0},
        {"lat": 1},
        {"lat": 1, "lng": 2, "alt": 3},
        "",
        "   ",
        "x" * 101,
        ["Dallas, TX"],
        42,
        None,
    ],
)
def test_bad_locations_are_rejected(location):
    ok, serializer = validate(start=location)
    assert not ok
    assert "start" in serializer.errors


def test_numbers_are_parsed_to_decimal_without_float_noise():
    ok, serializer = validate(
        start_fuel_gallons=20.1, reserve_gallons="5", min_saving_per_stop_usd=0.1
    )
    assert ok, serializer.errors
    data = serializer.validated_data
    assert data["start_fuel_gallons"] == Decimal("20.1")
    assert data["reserve_gallons"] == Decimal("5")
    assert data["min_saving_per_stop_usd"] == Decimal("0.1")
    assert all(isinstance(data[k], Decimal) for k in ("reserve_gallons", "corridor_miles"))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("corridor_miles", 0.5),
        ("corridor_miles", 26),
        ("reserve_gallons", -1),
        ("reserve_gallons", 26),
        ("min_saving_per_stop_usd", -0.01),
        ("min_saving_per_stop_usd", 101),
        ("start_fuel_gallons", -1),
        ("start_fuel_gallons", "lots"),
    ],
)
def test_out_of_range_values_name_the_field(field, value):
    ok, serializer = validate(**{field: value})
    assert not ok
    assert field in serializer.errors


def test_unknown_fields_are_rejected_by_name():
    ok, serializer = validate(min_saving_usd=5)
    assert not ok
    assert "min_saving_usd" in serializer.errors


def test_defaults(settings):
    settings.CORRIDOR_MILES = 12
    settings.DEFAULT_MIN_SAVING_PER_STOP_USD = 5
    ok, serializer = validate()
    assert ok
    data = serializer.validated_data
    assert data["start_fuel_gallons"] is None
    assert data["corridor_miles"] == Decimal(12)
    assert data["reserve_gallons"] == 0
    assert data["min_saving_per_stop_usd"] == Decimal(5)


def test_zero_min_saving_is_kept(settings):
    ok, serializer = validate(min_saving_per_stop_usd=0)
    assert ok
    assert serializer.validated_data["min_saving_per_stop_usd"] == 0


def test_start_and_finish_are_required():
    serializer = RoutePlanRequestSerializer(data={"start": "Dallas, TX"})
    assert not serializer.is_valid()
    assert "finish" in serializer.errors
