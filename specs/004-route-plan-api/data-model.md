# Data Model: Route Plan API (004)

No database tables. Value types live in pure modules; the HTTP shapes are in
[contracts/route_plan_api.md](contracts/route_plan_api.md).

## Locations (`planner/locations.py`, pure)

### `Place` (frozen dataclass)

`normalised_name: str`, `display_name: str`, `state: str`, `lat: float`, `lng: float`, `population: int`.

### `PlaceIndex` (frozen dataclass, `eq=False`)

| Field | Type | Notes |
| --- | --- | --- |
| `by_name` | `dict[tuple[str, str], Place]` | `(normalised_name, state)` from the file |
| `by_compact` | `dict[tuple[str, str], Place]` | `(compact_place_name, state)`; first by `(state, name)` order wins |
| `states` | `frozenset[str]` | The 51 codes in the file |
| `places` | `tuple[Place, ...]` | Same order as the tree |
| `tree` | `cKDTree` | Unit vectors of the places |

`load_place_index(path)` reads `data/places/us_places.csv.gz`; an empty or missing file raises
`PlaceDataMissing` (also for an unreadable file), whose message is "place data missing: data/places/us_places.csv.gz (restore it from git or rebuild with python manage.py build_station_data)".

### `ResolvedLocation` (frozen dataclass)

| Field | Type | Rules |
| --- | --- | --- |
| `query` | `str` | The input string, or `"lat,lng"` for coordinates |
| `lat`, `lng` | `float` | The place's coordinates for a city; the input for coordinates |
| `place_name` | `str \| None` | `"Dallas, TX"` style display name, if resolved from a name; returned as `name` in the response; for coordinates, the display name of the nearest place found by the inside-the-USA check |

### Errors

`LocationNotFound(query, message, field=None)`, `LocationOutsideUS(query, message, field=None)` (research R2 messages). The pure resolver leaves `field` empty; the service sets it to `"start"` or `"finish"` before re-raising, and the view returns it in `details.field`.

## Routing cache (`routing/cached.py`, pure)

`CachedRoutingProvider(provider: RoutingProvider, cache, ttl_seconds: int)`:
`route(start, finish) -> tuple[Route, bool]`; `cache_key(provider_name, start, finish) -> str`.
Successes only are stored (research R3).

## Fewer stops (`planner/fewer_stops.py`, pure)

### `FewerStopsResult` (frozen dataclass)

| Field | Type | Rules |
| --- | --- | --- |
| `plan` | `FuelPlan` | The returned plan |
| `cheapest` | `FuelPlan` | The 003 optimum |
| `stops_dropped` | `int` | ≥ 0; 0 when `min_saving_usd == 0` |
| `extra_cost_vs_cheapest_usd` | `Decimal` | `plan.total − cheapest.total`, ≥ 0, cents |

**Invariant (tested):** every stop in `plan` either saves at least `min_saving_usd` (re-planning
over the other stops costs that much more) or cannot be removed (re-planning is infeasible).

## Route output (`planner/route_output.py`, pure)

- `thin_line(points, max_points=5000) -> list[LatLng]`: every `ceil(n/max)`-th point plus the last.
- `point_at_mile(route, mile_miles) -> LatLng`: interpolated on the route, miles rescaled to `route.distance_miles`.
- `route_geojson(route_points, stops) -> dict`: the `FeatureCollection` (research R7).

## Service result (`api/services/route_plan.py`)

### `RoutePlanInput` (frozen dataclass)

`start`, `finish` (each `str` or `(lat, lng)`), `start_fuel_gallons: Decimal | None`,
`corridor_miles: Decimal` (default `CORRIDOR_MILES`), `reserve_gallons: Decimal` (0),
`min_saving_per_stop_usd: Decimal` (5).

### `RoutePlanResult` (frozen dataclass)

`start`, `finish: ResolvedLocation`; `route: Route`; `cached: bool`; `routing_calls: int`;
`candidates_count: int`; `result: FewerStopsResult`; `stations: dict[int, StationInfo]` (for the
stops); `stop_points: dict[int, tuple[float, float]]` (station lat/lng); `off_route_miles:
dict[int, float]`; `vehicle` (mpg, range, capacity); `timings_ms: dict[str, int]`.

### `InvalidPlanInput(field, message)`

Raised by the service for request values that depend on the vehicle (research R8); mapped to 400 `invalid_input` with `details = {"field": field, "fields": {field: [message]}}`.

### `SameLocation(query_start, query_finish, reason)`

Raised before routing (rounded coordinates equal) or after (route < 0.01 mi).

## Request validation (`api/serializers.py`)

| Field | Type | Rule | Default |
| --- | --- | --- | --- |
| `start`, `finish` | string or `{lat, lng}` | string: non-empty, ≤ 100 chars; lat −90..90, lng −180..180 | required |
| `start_fuel_gallons` | decimal | 0..capacity | full tank |
| `corridor_miles` | decimal | 1..25 | `CORRIDOR_MILES` (10) |
| `reserve_gallons` | decimal | 0..25, < capacity, ≤ start fuel | 0 |
| `min_saving_per_stop_usd` | decimal | 0..100 | `DEFAULT_MIN_SAVING_PER_STOP_USD` (5) |

Unknown fields are rejected (`invalid_input`) so a typo such as `min_saving_usd` is not silently ignored.

## Request flow

```text
validate ─▶ resolve start, finish ─▶ same rounded point? ─▶ SameLocation (400)
   │
cached route? ─yes─▶ route (0 calls) ─┐
   └─no─▶ provider.route (1 call) ────┤─▶ RoutingUnavailable (503)
                                      ▼
                       route < 0.01 mi? ─▶ SameLocation (400)
                                      ▼
            get_station_index ─▶ StationDataMissing (503)
                                      ▼
   find_candidates ─▶ to PlanStation (quantize, clamp, re-sort) ─▶ plan_with_min_saving
                                      │                                  └─▶ InfeasibleRoute (422)
                                      ▼
                 presenter: precision (R5), GeoJSON (R7), timings ─▶ 200
```
