"""T017: the route cache wrapper (pure, no Django: a dict-backed fake cache)."""

import ast
import inspect

import pytest

import routing.cached
from routing.base import LatLng, Route, RoutingFailure, RoutingUnavailable
from routing.cached import CachedRoutingProvider, cache_key

START, FINISH = LatLng(32.78, -96.8), LatLng(41.88, -87.63)
ROUTE = Route(points=(START, FINISH), distance_miles=966.45, provider="fake")


class FakeCache:
    def __init__(self):
        self.data, self.timeouts = {}, {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, timeout):
        self.data[key], self.timeouts[key] = value, timeout


class FakeProvider:
    name = "fake"

    def __init__(self, fail=False):
        self.calls, self.fail = 0, fail

    def route(self, start, finish):
        self.calls += 1
        if self.fail:
            raise RoutingUnavailable(RoutingFailure.TIMED_OUT, "timed out")
        return ROUTE


def test_miss_calls_once_and_stores_with_the_ttl():
    cache, provider = FakeCache(), FakeProvider()
    cached = CachedRoutingProvider(provider, cache, ttl_seconds=86400)
    assert cached.route(START, FINISH) == (ROUTE, False)
    assert provider.calls == 1
    key = cache_key("fake", START, FINISH)
    assert cache.data == {key: ROUTE}
    assert cache.timeouts[key] == 86400


def test_hit_makes_no_call():
    cache, provider = FakeCache(), FakeProvider()
    cached = CachedRoutingProvider(provider, cache, ttl_seconds=60)
    cached.route(START, FINISH)
    assert cached.route(START, FINISH) == (ROUTE, True)
    assert provider.calls == 1


def test_failures_are_not_cached():
    cache, provider = FakeCache(), FakeProvider(fail=True)
    cached = CachedRoutingProvider(provider, cache, ttl_seconds=60)
    for expected_calls in (1, 2):
        with pytest.raises(RoutingUnavailable):
            cached.route(START, FINISH)
        assert provider.calls == expected_calls
    assert cache.data == {}


def test_key_rounds_to_four_decimals():
    a = cache_key("osrm", LatLng(32.780049999, -96.8), FINISH)
    b = cache_key("osrm", LatLng(32.78004, -96.8), FINISH)
    c = cache_key("osrm", LatLng(32.78005001, -96.8), FINISH)
    assert a == b
    assert a != c


def test_key_treats_negative_zero_as_zero_and_names_the_provider():
    assert cache_key("osrm", LatLng(-0.00001, 0.0), FINISH) == cache_key(
        "osrm", LatLng(0.0, 0.0), FINISH
    )
    assert "osrm" in cache_key("osrm", START, FINISH)
    assert cache_key("osrm", START, FINISH) != cache_key("valhalla", START, FINISH)
    assert cache_key("osrm", START, FINISH) != cache_key("osrm", FINISH, START)


def test_cached_module_does_not_import_django():
    tree = ast.parse(inspect.getsource(routing.cached))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)

    assert not any(name.split(".")[0] == "django" for name in modules)
