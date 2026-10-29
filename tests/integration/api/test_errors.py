"""T021: every failure returns its documented status, code, message and details."""

import gzip

import httpx
import pytest

from stations.models import FuelStation
from tests.integration.api.conftest import API_URL, osrm_route, post

pytestmark = pytest.mark.django_db

TRIP = {"start": "Dallas, TX", "finish": "Chicago, IL"}
PLACE_MESSAGE = (
    "place data missing: data/places/us_places.csv.gz (restore it from git or rebuild with "
    "python manage.py build_station_data)"
)


def error(response, status, code):
    assert response.status_code == status, response.content
    body = response.json()
    assert list(body) == ["error"]
    assert list(body["error"]) == ["code", "message", "details"]
    assert body["error"]["code"] == code
    return body["error"]


# --- 400 invalid_input ---------------------------------------------------------------------


def test_malformed_json(client):
    response = client.post(API_URL, "{not json", content_type="application/json")
    error(response, 400, "invalid_input")


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"start": "Dallas, TX"}, "finish"),
        ({"start": {"lat": 200, "lng": 0}, "finish": "Chicago, IL"}, "start"),
        ({**TRIP, "min_saving_usd": 5}, "min_saving_usd"),
        ({**TRIP, "corridor_miles": 0.5}, "corridor_miles"),
        ({**TRIP, "corridor_miles": 26}, "corridor_miles"),
        ({**TRIP, "reserve_gallons": 26}, "reserve_gallons"),
        ({**TRIP, "min_saving_per_stop_usd": 101}, "min_saving_per_stop_usd"),
    ],
)
def test_request_validation_names_the_field(client, body, field):
    details = error(post(client, body), 400, "invalid_input")["details"]
    assert field in details["fields"]


@pytest.mark.parametrize(
    "extra", [{"start_fuel_gallons": 60}, {"start_fuel_gallons": 4, "reserve_gallons": 5}]
)
def test_values_that_do_not_fit_the_tank(client, osrm, extra):
    found = error(post(client, {**TRIP, **extra}), 400, "invalid_input")
    assert found["details"]["field"] == "start_fuel_gallons"
    assert "start_fuel_gallons" in found["message"]
    assert osrm.call_count == 0


# --- 400 locations -------------------------------------------------------------------------


def test_full_state_name_asks_for_a_two_letter_code(client):
    found = error(post(client, {**TRIP, "start": "Dallas, Texas"}), 400, "location_not_found")
    assert "2-letter state code" in found["message"]
    assert found["details"] == {"field": "start", "query": "Dallas, Texas"}


def test_unknown_city_names_the_side(client):
    found = error(post(client, {**TRIP, "finish": "Atlantis, TX"}), 400, "location_not_found")
    assert found["details"] == {"field": "finish", "query": "Atlantis, TX"}
    assert "Atlantis, TX" in found["message"]


@pytest.mark.parametrize(
    ("location", "query"),
    [({"lat": 19.43, "lng": -99.13}, "19.43,-99.13"), ("Toronto, ON", "Toronto, ON")],
)
def test_outside_the_us(client, location, query):
    found = error(post(client, {**TRIP, "start": location}), 400, "location_outside_us")
    assert found["details"] == {"field": "start", "query": query}


# --- 400 same_location ---------------------------------------------------------------------


def test_same_city_is_rejected_without_routing(client, osrm):
    found = error(
        post(client, {"start": "Dallas, TX", "finish": "dallas, tx"}), 400, "same_location"
    )
    assert found["details"] == {"start": "Dallas, TX", "finish": "dallas, tx"}
    assert osrm.call_count == 0


def test_points_across_a_rounding_boundary_hit_the_zero_length_guard(
    client, route_stations, respx_mock, settings
):
    a, b = (32.78004999, -96.8), (32.78005001, -96.8)
    respx_mock.get(url__startswith=settings.OSRM_BASE_URL).mock(
        return_value=httpx.Response(200, json=osrm_route([a, a], 0.5))
    )
    body = {"start": {"lat": a[0], "lng": a[1]}, "finish": {"lat": b[0], "lng": b[1]}}
    error(post(client, body), 400, "same_location")


def test_points_a_mile_apart_are_planned(client, route_stations, respx_mock, settings):
    a, b = (32.78, -96.8), (32.7945, -96.8)
    respx_mock.get(url__startswith=settings.OSRM_BASE_URL).mock(
        return_value=httpx.Response(200, json=osrm_route([a, b], 1609.344))
    )
    response = post(
        client, {"start": {"lat": a[0], "lng": a[1]}, "finish": {"lat": b[0], "lng": b[1]}}
    )
    assert response.status_code == 200, response.content
    assert response.json()["fuel_stops"] == []


# --- 422 infeasible_route ------------------------------------------------------------------


def test_station_gap(client, route_stations, osrm):
    FuelStation.objects.exclude(pk=101).delete()
    found = error(post(client, TRIP), 422, "infeasible_route")
    details = found["details"]
    assert details["reason"] == "station gap"
    assert details["gap_start_mile"] == pytest.approx(125.1, abs=0.5)  # station 101
    assert details["gap_end_mile"] == pytest.approx(966.452)  # the finish
    assert set(details["gap_start"]) == set(details["gap_end"]) == {"lat", "lng"}
    assert details["gap_end"] == {"lat": pytest.approx(41.880073), "lng": pytest.approx(-87.630002)}
    assert details["usable_range_miles"] == 500
    assert "start_fuel_gallons" not in details
    assert "station gap" in found["message"]


def test_start_fuel_too_low(client, route_stations, osrm):
    found = error(post(client, {**TRIP, "start_fuel_gallons": 0}), 422, "infeasible_route")
    details = found["details"]
    assert details["reason"] == "start fuel insufficient"
    assert (details["gap_start_mile"], details["start_fuel_gallons"]) == (0, 0)
    assert details["reserve_gallons"] == 0
    assert details["gallons_short"] == pytest.approx(details["gap_end_mile"] / 10)
    assert details["gap_start"] == {
        "lat": pytest.approx(32.779709),
        "lng": pytest.approx(-96.799911),
    }


# --- 503 -----------------------------------------------------------------------------------


def test_routing_timeout(client, route_stations, respx_mock, settings):
    respx_mock.get(url__startswith=settings.OSRM_BASE_URL).mock(
        side_effect=httpx.ReadTimeout("slow")
    )
    response = post(client, TRIP)
    found = error(response, 503, "routing_unavailable")
    assert found["details"] == {"reason": "timed out"}
    assert response["Retry-After"] == "30"


def test_rate_limited_passes_on_the_suggested_wait(client, route_stations, respx_mock, settings):
    respx_mock.get(url__startswith=settings.OSRM_BASE_URL).mock(
        return_value=httpx.Response(429, headers={"Retry-After": "2"})
    )
    response = post(client, TRIP)
    assert error(response, 503, "routing_unavailable")["details"] == {"reason": "rate limited"}
    assert response["Retry-After"] == "2"


def test_station_data_missing(client, osrm):
    found = error(post(client, TRIP), 503, "station_data_missing")
    assert "loaddata" in found["message"]


@pytest.mark.parametrize("failure", [FileNotFoundError("gone"), gzip.BadGzipFile("not gzip")])
def test_place_data_missing(client, monkeypatch, failure):
    def broken(*args, **kwargs):
        raise failure

    monkeypatch.setattr("planner.locations.gzip.open", broken)
    found = error(post(client, TRIP), 503, "place_data_missing")
    assert found["message"] == PLACE_MESSAGE


# --- 500 internal_error --------------------------------------------------------------------


def test_internal_error_is_not_reported_as_bad_input(
    client, route_stations, osrm, monkeypatch, caplog
):
    from api.services import route_plan

    original = route_plan.to_plan_stations

    def unsorted(candidates, distance):
        return list(reversed(original(candidates, distance)))

    monkeypatch.setattr("api.services.route_plan.to_plan_stations", unsorted)
    client.raise_request_exception = False
    response = post(client, TRIP)
    found = error(response, 500, "internal_error")
    assert found["message"] == "internal error"
    assert found["details"] == {}
    text = response.content.decode()
    assert "ValueError" not in text and "sorted" not in text and "Traceback" not in text
    assert any(r.exc_info and r.exc_info[0] is ValueError for r in caplog.records)


def test_a_failure_outside_the_service_is_also_internal_error(
    client, route_stations, osrm, monkeypatch, caplog
):
    def broken(result):
        raise KeyError("secret")

    monkeypatch.setattr("api.views.present", broken)
    client.raise_request_exception = False
    response = post(client, TRIP)
    found = error(response, 500, "internal_error")
    assert found["message"] == "internal error"
    text = response.content.decode()
    assert "KeyError" not in text and "secret" not in text and "Traceback" not in text
    assert any(r.exc_info and r.exc_info[0] is KeyError for r in caplog.records)
