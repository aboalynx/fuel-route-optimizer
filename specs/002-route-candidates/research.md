# Research: Route Candidates (002)

All decisions are final, and no NEEDS CLARIFICATION items remain. *Measured* values come from one
real call to the public OSRM server on 2026-10-29 (Dallas 32.78,-96.80 → Chicago 41.88,-87.63).

## R1. Routing provider and request shape

- **Decision:** OSRM public demo (`settings.OSRM_BASE_URL`), one `GET`:
  `/route/v1/driving/{lng},{lat};{lng},{lat}?overview=full&geometries=geojson`.
  Coordinates go **longitude first**.
- **Measured:**
  - HTTP 200, `code: "Ok"`, 0.50 s, 209 KB.
  - `routes[0].distance` = 1,555,353 m = **966.5 miles**.
  - `routes[0].geometry` is a GeoJSON `LineString` with **9,149** `[lng, lat]` points.
  - `waypoints[].distance` = 33.3 m and 8.1 m (snap distances, in meters).
- **Rationale:** no key, GeoJSON geometry (no polyline decoding), and the snap distances needed by FR-016 are in the same response.
- **Alternatives considered:**
  - Valhalla (truck costing): a stretch goal behind the same interface.
  - GraphHopper and Mapbox: need keys (constitution VIII).
  - OpenRouteService: unavailable at planning time.

## R2. Failure mapping (FR-006, FR-007, FR-016, FR-018)

- **Decision:** every failure raises `RoutingUnavailable(reason: RoutingFailure, detail: str, retry_after_seconds: int | None)`. There are **no retries**: each request makes exactly one call.

| Situation | `RoutingFailure` (value) |
| --- | --- |
| `httpx.TimeoutException` (connect or read) | `TIMED_OUT` ("timed out") |
| other `httpx.TransportError` | `NETWORK_ERROR` ("network error") |
| HTTP 429 | `RATE_LIMITED` ("rate limited"), with `retry_after_seconds` |
| other non-2xx (5xx, or 4xx other than below) | `SERVER_ERROR` ("server error") |
| body not JSON / missing fields / geometry not a LineString with ≥ 2 points | `INVALID_RESPONSE` ("invalid response") |
| `code` = `NoRoute`, or empty `routes` | `NO_ROUTE` ("no route found") |
| `code` = `NoSegment`, or any `waypoints[].distance` > 8,046.72 m (5 mi) | `NOT_NEAR_ROAD` ("start/finish not near a road") |

- **Retry-After:** used only when it's an integer number of seconds ≥ 0. It is capped at 60 (`min(int(v), 60)`). An HTTP-date or a missing header gives `None`.
- **Timeout:** `httpx.Timeout(settings.ROUTING_TIMEOUT_SECONDS)`. httpx applies one value to connect, read, write and pool separately, so a stalled read fails within the limit (FR-006).
- **Measured:** a point in the Atlantic returned `{"code": "NoRoute", "message": "Impossible route between points"}`.
- **Rationale:** a single error type keeps Feature 004's mapping simple (503 + retry hint). The enum follows the constitution's enum rule.
- **Alternatives considered:** retry with backoff (rejected: a second external call, which breaks principle II).

## R3. Corridor search: gather, then measure exactly (FR-008 to FR-012)

- **Decision:** as in [docs/algorithms/route-corridor-search.md](../../docs/algorithms/route-corridor-search.md) and the amended [ADR-0002](../../docs/adr/0002-kdtree-corridor-search.md).
  1. **densify** the route: keep every original point and insert linearly interpolated points so no segment is longer than `s = min(1 mi, r/2)`. Densified segments are sub-segments of the original polyline, so there is no corner-cutting on curves. Replacing the polyline with evenly spaced samples would cut corners: on a 1-mile-radius curve a 1-mile chord sits about 0.125 mi from the road, which breaks the 0.05-mile accuracy.
  2. Gather candidates with a `cKDTree` ball query on the densified points as 3D unit vectors (radius `r + s/2`).
  3. Measure each candidate exactly by projecting it onto the densified segments adjacent to its nearest densified point, using a local equirectangular projection.
  4. Include a station if and only if its off-route distance ≤ `r`.
  5. Rescale mile markers to the provider distance. Log a **warning** (not an error) when provider distance ÷ geometry length is outside 0.95–1.05; on real data that suggests a broken geometry.
- **Measured size:** the real route has 9,149 points over 966.5 mi (about 9.5 points per mile), so most segments are already shorter than 1 mi. Densifying keeps all of them and adds a few hundred points where vertices are far apart, about 9,500 in total. A ball query and a nearest-point query over ~10k points take milliseconds.
- **Accuracy:**
  - The flat approximation's error over 1-mile segments within ~11 mi is < 0.001 mi.
  - The densified polyline is the original polyline (only extra vertices on its own segments), so distances and mile markers are exact along it, before rescaling, including on curves.
  - Target: 0.05 mi (spec FR-011).
- **Alternatives considered:** see ADR-0002.

## R4. Station index (FR-013, FR-017)

- **Decision:**
  - **Pure part (`planner/station_index.py`):** a `StationIndex` dataclass holding parallel arrays (opis_id, lat, lng, unit vectors) plus per-station tuples (best_price `Decimal`, name, address, city, state, geo_source) and the `cKDTree`. `build_station_index(rows)` creates it. An empty input raises `StationDataMissing`.
  - **Django service (`stations/services/index_loader.py`; renamed so there are not two modules named `station_index`):** `get_station_index()` is wrapped in `functools.lru_cache(maxsize=1)` and reads `FuelStation` once with `values_list(...)` ordered by `opis_id`. It maps `OperationalError`/`ProgrammingError` (missing tables) and an empty table to `StationDataMissing("station data not loaded: run python manage.py loaddata stations")`.
  - **Reset:** tests call `get_station_index.cache_clear()`. New data needs a restart.
- **Rationale:** the index type stays pure, so corridor tests need no DB. Only the loader touches Django, which follows the services rule and principle III. Building the index from `values_list` takes milliseconds.
- **Alternatives considered:**
  - Building in `AppConfig.ready()`: rejected, because Django 5+ warns and it would run during `migrate`.
  - A module-level global: rejected, because it's harder to reset in tests than `cache_clear`.

## R5. Where settings are read

- **Decision:** `routing/base.py`, `routing/osrm.py`, `planner/*` and `planner/station_index.py` take plain arguments, with no Django import. Only two places read settings:
  - `routing/factory.py` (`provider_from_settings()`), for the provider name, base URL and timeout;
  - the station-index service.
  Feature 004 passes `CORRIDOR_MILES` in.
- **Rationale:** follows principle III and keeps every algorithm testable without Django.

## R6. Test strategy (constitution IV)

- **Routing:**
  - respx-mocked `httpx`, using a recorded fixture `tests/fixtures/osrm_dallas_chicago.json`. It's built from the real response above, trimmed to keep it small: distance, a short geometry, and waypoints. Because the real distance is kept, its geometry is much shorter than its distance. No test may assert geometry length ≈ distance on it.
  - Every failure row in R2 has a test asserting `respx` saw exactly 1 call.
- **Corridor:** synthetic routes (straight lines and two-point routes) at 31°N and 48°N, a looping route, and stations at exact offsets (9.99 / 10.01 mi, 0 mi). These need no DB and no network.
  - **Curve:** a synthetic arc (e.g. 1-mile radius) with a station on the arc reads off-route ≈ 0 (within 0.01 mi) and the correct arc-length mile marker (within 0.05 mi). This proves no corner-cutting.
  - **Densify:** every original point is kept, in order, and no segment is longer than the spacing.
  - **Rescale warning:** a geometry whose length differs from the provider distance by more than 5% logs a warning (caplog), and still returns candidates.
- **Station index:** pytest-django with the sample fixture from 001 (`tests/fixtures/stations_sample.json`). Covers the empty DB case → `StationDataMissing`, built once (`cache_info().misses == 1`), and `cache_clear()`.
- **Timing:** a smoke test on a synthetic 3,000-mile route with 6,600 random stations, run by hand and recorded in the README (SC-004). It's not asserted in CI.
- **Manual:** one real Dallas → Chicago call from the Django shell (SC-006). Expected ~966 mi.

## R7. Station index storage: in-process memory

- **Decision:** each server process holds its own `StationIndex` in memory. It is built once on first use by `stations/services/index_loader.py`, and searches never query the database.
- **Reasons:**
  - The data is small: 6,620 stations, about 1–2 MB including the KD-tree.
  - It is read-only, and changes only on a manual rebuild (followed by a restart).
  - It is built once per process in milliseconds.
  - The KD-tree has to live in the process that queries it.
- **Alternatives considered:**
  - **Redis as a cache for the index:** rejected. The KD-tree must live in the querying process, so Redis could only hold serialized bytes. Every request would pay a network round-trip plus deserialization, which is slower than having no cache. It also adds infrastructure and breaks the zero-setup reviewer run (constitution VII, VIII).
  - **Redis GEOSEARCH:** rejected. It searches around one point, but a route is a polyline of about 10,000 points, so it would take many calls per request. Mile markers and exact off-route distances would still have to be computed in Python.
- **Not to be confused with the route cache** (Feature 004, decision D11). That cache can move to Redis in production with a settings change. The station index stays in-process.
