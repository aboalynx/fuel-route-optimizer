# Contract: route-side interfaces used by Features 003 and 004

These are in-process Python interfaces. There is no HTTP surface in this feature. Types are in
[data-model.md](../data-model.md).

## Routing

```python
# routing/base.py (pure)
class RoutingProvider(Protocol):
    name: str

    def route(self, start: LatLng, finish: LatLng) -> Route: ...  # exactly 1 external call


# routing/osrm.py (pure; httpx)
class OSRMProvider:
    def __init__(
        self, base_url: str, timeout_seconds: float, client: httpx.Client | None = None
    ): ...


# routing/factory.py (the only routing module that reads Django settings)
def provider_from_settings() -> RoutingProvider: ...


#   ROUTING_PROVIDER: "osrm" (only value today); anything else ->
#   ImproperlyConfigured("unknown ROUTING_PROVIDER 'x'; allowed: osrm")
```

**Guarantees:**
- One call per `route()`, never retried.
- Success returns `Route` with ≥ 2 points and `distance_miles > 0`.
- Any failure raises `RoutingUnavailable`, with `reason`, `detail` and `retry_after_seconds` as in research R2.

**External request (OSRM):**

```text
GET {OSRM_BASE_URL}/route/v1/driving/{start.lng},{start.lat};{finish.lng},{finish.lat}
    ?overview=full&geometries=geojson
fields read: code, routes[0].distance (m), routes[0].geometry.coordinates ([lng, lat]),
             waypoints[].distance (m)
```

## Corridor search

```python
# planner/corridor.py (pure)
def find_candidates(
    route: Route,
    index: StationIndex,
    corridor_miles: float,  # 1..25, else ValueError
) -> list[Candidate]: ...
```

- **Order and inclusion:** sorted by `(mile_marker, opis_id)`; a station is included if and only if its exact off-route distance ≤ `corridor_miles`.
- **Determinism:** no I/O, the same output for the same input.

## Station index

```python
# planner/station_index.py (pure)
class StationDataMissing(Exception): ...


def build_station_index(rows: Iterable[StationInfoRow]) -> StationIndex: ...


# stations/services/index_loader.py (Django service)
@lru_cache(maxsize=1)
def get_station_index() -> StationIndex: ...


#   reads FuelStation once; missing tables or no rows -> StationDataMissing(
#   "station data not loaded: run python manage.py loaddata stations")
#   tests: get_station_index.cache_clear(); production never resets (restart for new data)
```

## Errors that cross into Feature 004

| Error | Feature 004 maps to |
| --- | --- |
| `RoutingUnavailable` | HTTP 503 `routing_unavailable`, `Retry-After` = `retry_after_seconds` or its default |
| `StationDataMissing` | HTTP 503 with the "station data not loaded" message |
| `ValueError` (radius out of 1–25) | HTTP 400 `invalid_input` |
