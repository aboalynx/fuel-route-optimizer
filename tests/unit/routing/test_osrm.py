"""T006: OSRM provider - one call per route, every failure mapped (respx, no network, no Django)."""

import json
from pathlib import Path

import httpx
import pytest

from routing.base import LatLng, RoutingFailure, RoutingUnavailable
from routing.osrm import OSRMProvider

BASE = "https://osrm.test"
URL = f"{BASE}/route/v1/driving/-96.8,32.78;-87.63,41.88"
FIXTURE = json.loads(
    (Path(__file__).resolve().parents[2] / "fixtures" / "osrm_dallas_chicago.json").read_text()
)
START, FINISH = LatLng(32.78, -96.8), LatLng(41.88, -87.63)


@pytest.fixture
def provider():
    return OSRMProvider(BASE, timeout_seconds=8)


def body(**changes):
    data = json.loads(json.dumps(FIXTURE))
    data.update(changes)
    return data


def failure(respx_mock, provider, **response):
    respx_mock.get(URL).mock(**response)
    with pytest.raises(RoutingUnavailable) as exc:
        provider.route(START, FINISH)
    assert respx_mock.calls.call_count == 1  # never retried
    return exc.value


# --- success -------------------------------------------------------------------------------


def test_request_uses_lng_lat_order_and_geojson(respx_mock, provider):
    route = respx_mock.get(URL, params={"overview": "full", "geometries": "geojson"}).mock(
        return_value=httpx.Response(200, json=FIXTURE)
    )

    provider.route(START, FINISH)

    assert route.called
    assert respx_mock.calls.call_count == 1


def test_success_converts_meters_and_swaps_coordinates(respx_mock, provider):
    respx_mock.get(URL).mock(return_value=httpx.Response(200, json=FIXTURE))

    route = provider.route(START, FINISH)

    assert route.distance_miles == pytest.approx(1555353 / 1609.344)
    assert route.distance_miles == pytest.approx(966.45, abs=0.01)
    assert route.points[0] == LatLng(32.779709, -96.799911)
    assert len(route.points) == len(FIXTURE["routes"][0]["geometry"]["coordinates"])
    assert route.provider == "osrm"
    assert respx_mock.calls.call_count == 1


def test_timeout_covers_connect_and_each_read(provider):
    assert provider.client.timeout == httpx.Timeout(8)


# --- transport failures --------------------------------------------------------------------


@pytest.mark.parametrize("error", [httpx.ConnectTimeout("slow"), httpx.ReadTimeout("stalled")])
def test_timeouts(respx_mock, provider, error):
    assert failure(respx_mock, provider, side_effect=error).reason is RoutingFailure.TIMED_OUT


def test_network_error(respx_mock, provider):
    error = failure(respx_mock, provider, side_effect=httpx.ConnectError("refused"))
    assert error.reason is RoutingFailure.NETWORK_ERROR


# --- HTTP status ---------------------------------------------------------------------------


def test_server_error(respx_mock, provider):
    error = failure(respx_mock, provider, return_value=httpx.Response(500, text="boom"))
    assert error.reason is RoutingFailure.SERVER_ERROR


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        ({"code": "NoRoute", "message": "Impossible route"}, RoutingFailure.NO_ROUTE),
        (
            {"code": "NoSegment", "message": "Could not find a segment"},
            RoutingFailure.NOT_NEAR_ROAD,
        ),
        (
            {"code": "InvalidQuery", "message": "Query string malformed"},
            RoutingFailure.SERVER_ERROR,
        ),
    ],
)
def test_http_400_uses_the_osrm_code(respx_mock, provider, payload, reason):
    error = failure(respx_mock, provider, return_value=httpx.Response(400, json=payload))
    assert error.reason is reason


def test_http_400_without_json_is_a_server_error(respx_mock, provider):
    error = failure(respx_mock, provider, return_value=httpx.Response(400, text="<html>bad</html>"))
    assert error.reason is RoutingFailure.SERVER_ERROR


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({"Retry-After": "2"}, 2),
        ({}, None),
        ({"Retry-After": "3600"}, 60),
        ({"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}, None),
    ],
)
def test_rate_limited(respx_mock, provider, headers, expected):
    error = failure(respx_mock, provider, return_value=httpx.Response(429, headers=headers))

    assert error.reason is RoutingFailure.RATE_LIMITED
    assert error.retry_after_seconds == expected


# --- response body -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"code": "Ok"}),  # no routes
        httpx.Response(200, json=body(routes=[{"distance": 10, "geometry": {"type": "Point"}}])),
        httpx.Response(
            200,
            json=body(
                routes=[
                    {"distance": 10, "geometry": {"type": "LineString", "coordinates": [[0, 0]]}}
                ]
            ),
        ),
    ],
    ids=["not-json", "no-routes-key", "not-a-linestring", "one-point"],
)
def test_invalid_response(respx_mock, provider, response):
    error = failure(respx_mock, provider, return_value=response)
    assert error.reason is RoutingFailure.INVALID_RESPONSE


@pytest.mark.parametrize(
    "payload",
    [{"code": "NoRoute", "message": "Impossible route between points"}, body(routes=[])],
    ids=["code-noroute", "empty-routes"],
)
def test_no_route(respx_mock, provider, payload):
    error = failure(respx_mock, provider, return_value=httpx.Response(200, json=payload))
    assert error.reason is RoutingFailure.NO_ROUTE


def test_nosegment_code_is_not_near_road(respx_mock, provider):
    error = failure(
        respx_mock, provider, return_value=httpx.Response(200, json={"code": "NoSegment"})
    )
    assert error.reason is RoutingFailure.NOT_NEAR_ROAD


def snapped(meters):
    data = body()
    data["waypoints"][1]["distance"] = meters
    return data


def test_snap_beyond_five_miles_is_not_near_road(respx_mock, provider):
    error = failure(respx_mock, provider, return_value=httpx.Response(200, json=snapped(8046.73)))
    assert error.reason is RoutingFailure.NOT_NEAR_ROAD


def test_snap_of_exactly_five_miles_is_accepted(respx_mock, provider):
    respx_mock.get(URL).mock(return_value=httpx.Response(200, json=snapped(8046.72)))

    assert provider.route(START, FINISH).provider == "osrm"
    assert respx_mock.calls.call_count == 1
