"""T004: shared routing value types (pure, no Django)."""

import ast
import dataclasses
import inspect

import pytest

import routing.base
from routing.base import LatLng, Route, RoutingFailure, RoutingUnavailable


def test_latlng_and_route_are_frozen():
    point = LatLng(32.78, -96.80)
    route = Route(points=(point, LatLng(41.88, -87.63)), distance_miles=966.5, provider="osrm")

    with pytest.raises(dataclasses.FrozenInstanceError):
        point.lat = 0
    with pytest.raises(dataclasses.FrozenInstanceError):
        route.distance_miles = 0


def test_routing_failure_values():
    assert {member.name: member.value for member in RoutingFailure} == {
        "TIMED_OUT": "timed out",
        "NETWORK_ERROR": "network error",
        "SERVER_ERROR": "server error",
        "RATE_LIMITED": "rate limited",
        "INVALID_RESPONSE": "invalid response",
        "NO_ROUTE": "no route found",
        "NOT_NEAR_ROAD": "start/finish not near a road",
    }


def test_routing_unavailable_carries_reason_detail_and_wait():
    error = RoutingUnavailable(RoutingFailure.RATE_LIMITED, "HTTP 429", retry_after_seconds=2)

    assert error.reason is RoutingFailure.RATE_LIMITED
    assert error.detail == "HTTP 429"
    assert error.retry_after_seconds == 2
    assert "rate limited" in str(error)
    assert "HTTP 429" in str(error)


def test_retry_after_defaults_to_none():
    assert RoutingUnavailable(RoutingFailure.TIMED_OUT, "8s").retry_after_seconds is None


def test_base_module_does_not_import_django():
    tree = ast.parse(inspect.getsource(routing.base))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)

    assert not any(name.split(".")[0] == "django" for name in modules)
