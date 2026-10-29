"""Route cache around any provider (pure: the cache object is passed in).

Stores the route only, never the plan, so a hit cannot change the plan (constitution VII). Only
successes are stored; a failure is raised and the next request tries the provider again.
"""

from routing.base import LatLng, Route, RoutingProvider

KEY_VERSION = "v1"


def cache_key(provider_name: str, start: LatLng, finish: LatLng) -> str:
    """Coordinates rounded to 4 decimal places (~11 m); -0.0 and 0.0 share a key."""

    def point(p: LatLng) -> str:
        return f"{round(p.lat, 4) + 0.0:.4f},{round(p.lng, 4) + 0.0:.4f}"

    return f"route:{KEY_VERSION}:{provider_name}:{point(start)};{point(finish)}"


class CachedRoutingProvider:
    def __init__(self, provider: RoutingProvider, cache, ttl_seconds: int):
        self.provider = provider
        self.cache = cache  # anything with get(key) and set(key, value, timeout)
        self.ttl_seconds = ttl_seconds

    @property
    def name(self) -> str:
        return self.provider.name

    def route(self, start: LatLng, finish: LatLng) -> tuple[Route, bool]:
        """(route, came from the cache?). A miss makes exactly one provider call."""
        key = cache_key(self.provider.name, start, finish)
        cached = self.cache.get(key)
        if cached is not None:
            return cached, True
        route = self.provider.route(start, finish)
        self.cache.set(key, route, timeout=self.ttl_seconds)
        return route, False
