"""OSRM routing provider: one HTTP call per route, every failure mapped (pure, no Django).

Mapping order (research R2): transport errors, HTTP 429, other 4xx by their OSRM code, other
non-2xx, then the JSON body. No call is ever retried: a retry would be a second external call.
"""

import httpx

from routing.base import LatLng, Route, RoutingFailure, RoutingUnavailable

METERS_PER_MILE = 1609.344
MAX_SNAP_METERS = 8046.72  # 5 miles: farther than this, the start/finish is not near a road
MAX_RETRY_AFTER_SECONDS = 60

# OSRM codes in an error body, and what they mean for the caller.
_CODE_FAILURES = {"NoRoute": RoutingFailure.NO_ROUTE, "NoSegment": RoutingFailure.NOT_NEAR_ROAD}


class OSRMProvider:
    name = "osrm"

    def __init__(self, base_url: str, timeout_seconds: float, client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        # One value applies to connect, read, write and pool separately.
        self.client = client or httpx.Client(timeout=httpx.Timeout(timeout_seconds))

    def route(self, start: LatLng, finish: LatLng) -> Route:
        url = (
            f"{self.base_url}/route/v1/driving/"
            f"{start.lng},{start.lat};{finish.lng},{finish.lat}"  # OSRM wants lng,lat
        )
        try:
            response = self.client.get(url, params={"overview": "full", "geometries": "geojson"})
        except httpx.TimeoutException as error:
            raise RoutingUnavailable(RoutingFailure.TIMED_OUT, str(error) or "timed out") from error
        except httpx.TransportError as error:
            raise RoutingUnavailable(RoutingFailure.NETWORK_ERROR, str(error)) from error

        _raise_for_status(response)
        return _parse_route(response)


def _raise_for_status(response: httpx.Response) -> None:
    status = response.status_code
    if status == 429:
        raise RoutingUnavailable(
            RoutingFailure.RATE_LIMITED,
            "HTTP 429",
            retry_after_seconds=_retry_after(response.headers.get("Retry-After")),
        )
    if 400 <= status < 500:
        code = _json_code(response)
        reason = _CODE_FAILURES.get(code, RoutingFailure.SERVER_ERROR)
        raise RoutingUnavailable(reason, f"HTTP {status} {code or ''}".strip())
    if not 200 <= status < 300:
        raise RoutingUnavailable(RoutingFailure.SERVER_ERROR, f"HTTP {status}")


def _parse_route(response: httpx.Response) -> Route:
    try:
        data = response.json()
    except ValueError as error:
        raise RoutingUnavailable(RoutingFailure.INVALID_RESPONSE, "body is not JSON") from error
    if not isinstance(data, dict):
        raise RoutingUnavailable(RoutingFailure.INVALID_RESPONSE, "body is not an object")

    code = data.get("code")
    if code in _CODE_FAILURES:
        raise RoutingUnavailable(_CODE_FAILURES[code], data.get("message") or code)
    if code != "Ok":
        raise RoutingUnavailable(RoutingFailure.SERVER_ERROR, f"code {code!r}")
    if "routes" not in data:
        raise RoutingUnavailable(RoutingFailure.INVALID_RESPONSE, "no routes in the response")
    if not data["routes"]:
        raise RoutingUnavailable(RoutingFailure.NO_ROUTE, "empty routes")

    for waypoint in data.get("waypoints") or []:
        if waypoint.get("distance", 0) > MAX_SNAP_METERS:
            raise RoutingUnavailable(
                RoutingFailure.NOT_NEAR_ROAD,
                f"snapped {waypoint['distance'] / METERS_PER_MILE:.1f} miles to reach a road",
            )

    try:
        route = data["routes"][0]
        geometry = route["geometry"]
        coordinates = geometry["coordinates"]
        distance_meters = float(route["distance"])
        if geometry["type"] != "LineString" or len(coordinates) < 2:
            raise ValueError("geometry is not a LineString with at least 2 points")
        points = tuple(LatLng(lat=float(lat), lng=float(lng)) for lng, lat, *_ in coordinates)
    except (KeyError, TypeError, ValueError) as error:
        raise RoutingUnavailable(RoutingFailure.INVALID_RESPONSE, str(error)) from error

    return Route(points=points, distance_miles=distance_meters / METERS_PER_MILE, provider="osrm")


def _json_code(response: httpx.Response) -> str | None:
    try:
        data = response.json()
    except ValueError:
        return None
    return data.get("code") if isinstance(data, dict) else None


def _retry_after(value: str | None) -> int | None:
    """Whole seconds only (an HTTP-date gives None), capped at 60."""
    if value is None:
        return None
    value = value.strip()
    if not (value.isascii() and value.isdigit()):
        return None
    return min(int(value), MAX_RETRY_AFTER_SECONDS)
