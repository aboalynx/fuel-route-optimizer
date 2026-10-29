"""T018: a repeated route is served from the cache with 0 routing calls and the same plan."""

import httpx
import pytest

from tests.integration.api.conftest import ROUTE_JSON, post

pytestmark = pytest.mark.django_db

TRIP = {"start": "Dallas, TX", "finish": "Chicago, IL"}


def test_repeat_request_uses_the_cache(client, route_stations, osrm):
    first = post(client, TRIP).json()
    second = post(client, TRIP).json()
    assert (first["meta"]["routing_calls"], first["meta"]["cached"]) == (1, False)
    assert (second["meta"]["routing_calls"], second["meta"]["cached"]) == (0, True)
    assert osrm.call_count == 1
    assert first["summary"] == second["summary"]
    assert first["fuel_stops"] == second["fuel_stops"]


@pytest.mark.parametrize(
    "option",
    [
        {"start_fuel_gallons": 30},
        {"corridor_miles": 5},
        {"reserve_gallons": 3},
        {"min_saving_per_stop_usd": 5},
    ],
)
def test_other_options_reuse_the_route_and_replan(client, route_stations, osrm, option):
    post(client, TRIP)
    response = post(client, {**TRIP, **option}).json()
    assert response["meta"]["routing_calls"] == 0
    assert osrm.call_count == 1
    key = next(iter(option))
    assert response["summary"]["assumptions"][key] == option[key]


def test_coordinates_beyond_the_fourth_decimal_share_the_route(client, route_stations, osrm):
    post(client, {"start": {"lat": 32.780001, "lng": -96.8}, "finish": "Chicago, IL"})
    second = post(client, {"start": {"lat": 32.780049, "lng": -96.8}, "finish": "Chicago, IL"})
    assert second.json()["meta"]["routing_calls"] == 0
    assert osrm.call_count == 1


def test_a_failed_route_is_not_cached(client, route_stations, respx_mock, settings):
    route = respx_mock.get(url__startswith=settings.OSRM_BASE_URL)
    route.side_effect = [httpx.ReadTimeout("slow"), httpx.Response(200, json=ROUTE_JSON)]
    assert post(client, TRIP).status_code == 503
    retry = post(client, TRIP)
    assert retry.status_code == 200
    assert retry.json()["meta"]["routing_calls"] == 1
    assert route.call_count == 2
