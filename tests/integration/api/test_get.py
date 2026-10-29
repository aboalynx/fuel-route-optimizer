"""T030: the optional GET form returns the same plan as the POST."""

import pytest

from tests.integration.api.conftest import API_URL, post

pytestmark = pytest.mark.django_db


def test_get_matches_post(client, route_stations, osrm):
    by_post = post(client, {"start": "Dallas, TX", "finish": "Chicago, IL"}).json()
    by_get = client.get(API_URL, {"start": "Dallas, TX", "finish": "Chicago, IL"})
    assert by_get.status_code == 200, by_get.content
    assert by_get.json()["summary"] == by_post["summary"]
    assert by_get.json()["fuel_stops"] == by_post["fuel_stops"]


def test_get_with_coordinates_and_options(client, route_stations, osrm):
    response = client.get(
        API_URL,
        {"start": "32.78,-96.80", "finish": "Chicago, IL", "min_saving_per_stop_usd": "5"},
    )
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["start"]["query"] == "32.78,-96.8"
    assert body["summary"]["assumptions"]["min_saving_per_stop_usd"] == 5


def test_get_with_a_bad_parameter(client):
    response = client.get(
        API_URL, {"start": "Dallas, TX", "finish": "Chicago, IL", "corridor_miles": "99"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_input"
    assert "corridor_miles" in response.json()["error"]["details"]["fields"]
