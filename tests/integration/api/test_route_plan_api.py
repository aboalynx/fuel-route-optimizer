"""T012: the route-plan endpoint end to end (respx-mocked OSRM, route-plan station fixture)."""

import logging
from decimal import Decimal

import httpx
import pytest

from tests.integration.api.conftest import osrm_route, post

pytestmark = pytest.mark.django_db

TRIP = {"start": "Dallas, TX", "finish": "Chicago, IL"}


def test_happy_path_shape_and_one_routing_call(client, route_stations, osrm):
    response = post(client, TRIP)
    assert response.status_code == 200, response.content
    body = response.json()
    assert list(body) == ["start", "finish", "summary", "fuel_stops", "map", "meta"]
    assert body["start"]["name"] == "Dallas, TX"
    assert body["finish"]["name"] == "Chicago, IL"
    assert body["meta"]["routing_calls"] == 1
    assert body["meta"]["cached"] is False
    assert body["meta"]["routing_provider"] == "osrm"
    assert osrm.call_count == 1
    assert body["meta"]["candidate_stations_considered"] == 4  # pk 105 is 30 mi away
    assert set(body["meta"]["timings_ms"]) == {
        "resolve",
        "routing",
        "candidates",
        "optimize",
        "total",
    }

    stops = body["fuel_stops"]
    assert stops, "the 966-mile trip needs at least one stop"
    assert [s["sequence"] for s in stops] == list(range(1, len(stops) + 1))
    assert [s["mile_marker"] for s in stops] == sorted(s["mile_marker"] for s in stops)
    assert 105 not in [s["opis_id"] for s in stops]
    total = sum(Decimal(str(s["cost_usd"])) for s in stops)
    assert Decimal(str(body["summary"]["total_fuel_cost_usd"])) == total
    for s in stops:
        product = Decimal(str(s["gallons"])) * Decimal(str(s["price_usd_per_gallon"]))
        assert abs(product - Decimal(str(s["cost_usd"]))) <= Decimal("0.005")
    assert body["map"]["features"][0]["geometry"]["type"] == "LineString"
    assert len(body["map"]["features"]) == 1 + len(stops)


def test_the_trimmed_fixture_logs_the_expected_scaling_warning_once(
    client, route_stations, osrm, caplog
):
    with caplog.at_level(logging.WARNING, logger="planner.corridor"):
        assert post(client, TRIP).status_code == 200
    warnings = [r for r in caplog.records if r.name == "planner.corridor"]
    assert len(warnings) == 1
    assert "route geometry" in warnings[0].getMessage()


def test_coordinates_work_like_names(client, route_stations, osrm):
    response = post(client, {"start": {"lat": 32.78, "lng": -96.80}, "finish": "Chicago, IL"})
    assert response.status_code == 200, response.content
    start = response.json()["start"]
    assert start["query"] == "32.78,-96.8"
    assert start["name"] == "Dallas, TX"
    assert (start["lat"], start["lng"]) == (32.78, -96.8)


def test_defaults_and_options_are_echoed(client, route_stations, osrm):
    defaults = post(client, TRIP).json()["summary"]["assumptions"]
    assert defaults == {
        "mpg": 10,
        "max_range_miles": 500,
        "tank_capacity_gallons": 50,
        "start_fuel_gallons": 50,
        "corridor_miles": 10,
        "reserve_gallons": 0,
        "min_saving_per_stop_usd": 5,
    }
    options = {
        "start_fuel_gallons": 40,
        "corridor_miles": 12,
        "reserve_gallons": 2,
        "min_saving_per_stop_usd": 1.5,
    }
    echoed = post(client, {**TRIP, **options}).json()["summary"]["assumptions"]
    assert {k: echoed[k] for k in options} == options


def test_short_trip_on_a_full_tank_has_no_stops(client, route_stations, respx_mock, settings):
    respx_mock.get(url__startswith=settings.OSRM_BASE_URL).mock(
        return_value=httpx.Response(
            200, json=osrm_route([(32.78, -96.80), (36.0, -96.80)], 300 * 1609.344)
        )
    )
    response = post(client, {"start": "Dallas, TX", "finish": {"lat": 36.0, "lng": -96.8}})
    assert response.status_code == 200, response.content
    summary = response.json()["summary"]
    assert response.json()["fuel_stops"] == []
    assert summary["total_fuel_cost_usd"] == 0
    assert summary["fuel_left_gallons"] == 20


def test_same_request_same_plan(client, route_stations, osrm):
    first, second = post(client, TRIP).json(), post(client, TRIP).json()
    assert first["summary"] == second["summary"]
    assert first["fuel_stops"] == second["fuel_stops"]


def test_later_requests_query_no_station_data(
    client, route_stations, osrm, django_assert_num_queries
):
    post(client, TRIP)
    with django_assert_num_queries(0):
        assert post(client, TRIP).status_code == 200


def test_min_saving_per_stop_is_reported(client, route_stations, osrm):
    plain = post(client, {**TRIP, "min_saving_per_stop_usd": 0}).json()["summary"]
    assert (plain["stops_dropped"], plain["extra_cost_vs_cheapest_usd"]) == (0, 0)
    assert plain["minimum_possible_cost_usd"] == plain["total_fuel_cost_usd"]

    summary = post(client, TRIP).json()["summary"]  # the default is 5
    assert summary == post(client, {**TRIP, "min_saving_per_stop_usd": 5}).json()["summary"]
    assert summary["assumptions"]["min_saving_per_stop_usd"] == 5
    assert summary["minimum_possible_cost_usd"] == plain["total_fuel_cost_usd"]
    extra = Decimal(str(summary["extra_cost_vs_cheapest_usd"]))
    difference = Decimal(str(summary["total_fuel_cost_usd"])) - Decimal(
        str(plain["total_fuel_cost_usd"])
    )
    assert extra == difference >= 0
    assert summary["stops_count"] + summary["stops_dropped"] == plain["stops_count"]
