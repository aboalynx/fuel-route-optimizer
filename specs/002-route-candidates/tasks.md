---

description: "Task list for Feature 002: Route Candidates"
---

# Tasks: Route Candidates

**Input**: Design documents from `specs/002-route-candidates/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/route_candidates.md, quickstart.md

**Tests**: Required (constitution IV: test-first, offline).

- Each test file is written first and run to show it failing (import or assertion errors) before its module exists. That output is the test-first record.
- No test touches the network: respx mocks httpx, and geometry uses synthetic routes.

**Organization**: US1 is the routing call and US2 is the corridor search. The shared value types (`routing/base.py`) are foundational, because both stories use `Route`.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on unfinished tasks)
- **[Story]**: US1 / US2 from spec.md
- Paths are repo-relative; `routing/` and `planner/` are plain packages (not Django apps)

---

## Phase 1: Setup

- [ ] T001 Create the test packages `tests/unit/routing/__init__.py` and `tests/unit/planner/__init__.py` (empty).
- [ ] T002 [P] Create `tests/fixtures/osrm_dallas_chicago.json` by trimming the real OSRM response recorded in research R1. If that recording is unavailable, fetch it once with the R1 `curl`. Keep:
  - `code: "Ok"`;
  - `routes[0].distance` = `1555353` (meters);
  - `routes[0].geometry` as a GeoJSON `LineString` of about 50 `[lng, lat]` points, taken evenly from the real geometry and including the first and last points;
  - `waypoints` exactly as recorded (`distance` 33.33… m and 8.10… m, with `location` and `name`).

  Add no other keys. **Note:** the geometry is far shorter than the distance on purpose. No test may assert geometry length ≈ distance on this fixture (plan, "Recorded fixture").
- [ ] T003 [P] Add synthetic-route helpers in `tests/unit/planner/conftest.py`:
  - `offset(lat, lng, north_miles, east_miles) -> (lat, lng)`, using the local equirectangular frame with `M = π·3958.8/180` mi per degree;
  - `straight_route(lat, lng, bearing, miles, step_miles)`;
  - `arc_route(center_lat, center_lng, radius_miles, start_deg, end_deg, n_points)`;
  - a `make_index(stations)` fixture that builds a `StationIndex` from `(opis_id, lat, lng, price)` tuples, via `planner.station_index.build_station_index`.

---

## Phase 2: Foundational (blocking)

**Purpose**: shared value types used by both stories (`Route`, `LatLng`, routing errors).

- [ ] T004 Write the failing test `tests/unit/routing/test_base.py` (pure, no Django), covering:
  - `LatLng` and `Route` are frozen dataclasses;
  - the `RoutingFailure` `StrEnum` values are exactly: `TIMED_OUT="timed out"`, `NETWORK_ERROR="network error"`, `SERVER_ERROR="server error"`, `RATE_LIMITED="rate limited"`, `INVALID_RESPONSE="invalid response"`, `NO_ROUTE="no route found"`, `NOT_NEAR_ROAD="start/finish not near a road"`;
  - `RoutingUnavailable(reason, detail, retry_after_seconds=None)` exposes those three attributes, and its `str()` contains the reason value and the detail;
  - `routing/base.py` imports no Django (an AST check like `tests/unit/stations/test_enums.py`).
- [ ] T005 Implement `routing/base.py`: `LatLng(lat: float, lng: float)`, `Route(points: tuple[LatLng, ...], distance_miles: float, provider: str)`, `RoutingFailure`, `RoutingUnavailable`, and a `RoutingProvider` `Protocol` (`name: str`, `route(start, finish) -> Route`), as in data-model.md. Run T004 green.

**Checkpoint**: shared types exist; both stories can start.

---

## Phase 3: User Story 1 - Get a driving route with exactly one external call (Priority: P1) 🎯 MVP

**Goal**: `OSRMProvider.route()` makes exactly one HTTP call and returns a `Route`. Every failure becomes `RoutingUnavailable`, with no retries.

**Independent Test**: all of `tests/unit/routing/` passes offline with respx (spec SC-001, SC-002).

### Tests for User Story 1 ⚠️ (write first, show failing)

- [ ] T006 [P] [US1] Write `tests/unit/routing/test_osrm.py` (respx, no Django). Every test asserts `respx_mock.calls.call_count == 1`. Cases:
  - **Request:** a `GET` to `{base}/route/v1/driving/-96.8,32.78;-87.63,41.88` with `overview=full&geometries=geojson` (longitude first).
  - **Success** (fixture T002): `distance_miles == 1555353 / 1609.344` (966.45…); `points[0] == LatLng(32.779709, -96.799911)` (lat/lng swapped from GeoJSON); `provider == "osrm"`.
  - **Timeouts:** `httpx.ConnectTimeout` and `httpx.ReadTimeout` → `TIMED_OUT`.
  - **Network:** `httpx.ConnectError` → `NETWORK_ERROR`.
  - **Server errors:** HTTP 500 → `SERVER_ERROR`.
  - **HTTP 400 with an OSRM code in the JSON body** (OSRM reports errors this way):
    - `400` + `{"code": "NoRoute"}` → `NO_ROUTE`;
    - `400` + `{"code": "NoSegment"}` → `NOT_NEAR_ROAD`;
    - `400` + `{"code": "InvalidQuery"}` → `SERVER_ERROR`;
    - `400` with a body that is not JSON → `SERVER_ERROR`.
  - **Rate limiting:** HTTP 429 with:
    - `Retry-After: 2` → `RATE_LIMITED`, `retry_after_seconds == 2`;
    - no header → `None`;
    - `Retry-After: 3600` → `60`;
    - an HTTP-date `Retry-After` → `None`.
  - **Invalid responses:** body not JSON; missing `routes`; geometry not a `LineString` or with < 2 points → `INVALID_RESPONSE`.
  - **No route:** `code: "NoRoute"`, or `routes: []` → `NO_ROUTE`.
  - **Not near a road:**
    - `code: "NoSegment"` → `NOT_NEAR_ROAD`;
    - a waypoint `distance` of `8046.73` m → `NOT_NEAR_ROAD`;
    - a waypoint `distance` of `8046.72` m → success (the limit is 5 mi inclusive).
  - **Timeout config:** the provider's client uses `httpx.Timeout(timeout_seconds)`, so the limit covers connect and each read.
- [ ] T007 [P] [US1] Write `tests/unit/routing/test_factory.py` (pytest-django `settings` fixture), covering:
  - `ROUTING_PROVIDER="osrm"` → an `OSRMProvider` using `OSRM_BASE_URL` and `ROUTING_TIMEOUT_SECONDS`;
  - `ROUTING_PROVIDER="valhalla"` → `ImproperlyConfigured`, with a message that names the bad value and lists `osrm`.

### Implementation for User Story 1

- [ ] T008 [US1] Implement `routing/osrm.py`, `OSRMProvider(base_url, timeout_seconds, client=None)`:
  - one `client.get(...)` per `route()`, with no retry loop anywhere;
  - map failures exactly as in research R2, in this order: 429 first; then, for any other 4xx, parse the JSON `code` of the body (`NoRoute` → `NO_ROUTE`, `NoSegment` → `NOT_NEAR_ROAD`, any other code or a non-JSON body → `SERVER_ERROR`) before the generic non-2xx mapping; `Retry-After` is accepted only as an integer string ≥ 0, then `min(v, 60)`; the snap limit is `MAX_SNAP_METERS = 5 * 1609.344`;
  - convert meters to miles by `/ 1609.344`, and GeoJSON `[lng, lat]` to `LatLng(lat, lng)`;
  - no Django import.

  Run T006 green.
- [ ] T009 [US1] Implement `routing/factory.py`, `provider_from_settings()`. It reads `settings.ROUTING_PROVIDER`, `OSRM_BASE_URL` and `ROUTING_TIMEOUT_SECONDS`; the allowed providers are the dict `{"osrm": OSRMProvider}`; an unknown name raises `ImproperlyConfigured`. This is the only routing module that imports Django. Run T007 green.

**Checkpoint**: US1 is complete and testable offline. `quickstart.md` §2 (one real call) can be run by hand.

---

## Phase 4: User Story 2 - Find the fuel stations along a route (Priority: P2)

**Goal**: `find_candidates(route, index, corridor_miles)` returns every station within the radius. It has exact mile markers and off-route distances (0.05 mi), a station on the route reads 0, the list is sorted by `(mile_marker, opis_id)`, and candidates carry the exact `Decimal` price. The station index is loaded once and never queried per search.

**Independent Test**:

- `tests/unit/planner/` passes on synthetic routes, with no DB and no network;
- `tests/integration/test_index_loader.py` passes against the 001 sample fixture.

### Tests for User Story 2 ⚠️ (write first, show failing)

- [ ] T010 [P] [US2] Write `tests/unit/planner/test_geometry.py` (pure), covering:
  - **`haversine_miles`:** Dallas (32.78, -96.80) → Chicago (41.88, -87.63) ≈ 804.7 mi great-circle with R = 3958.8 mi (±1); 0 for the same point.
  - **`densify(points, spacing)`:**
    - every original point is kept, in order;
    - no segment is longer than `spacing` (+1e-9);
    - on a 2-point route, the point count == `ceil(haversine length / spacing) + 1`;
    - a route already finer than the spacing is unchanged.
  - **`cumulative_miles`:** starts at 0 and is non-decreasing; the last value equals the summed haversine.
  - **Unit vectors and chords:** `to_unit_vectors` rows have norm 1; `arc_miles(chord_for_miles(x)) ≈ x`.
  - **`project_onto_segment`** (local equirectangular frame around the station): a point on the segment → distance 0 and the right fraction `t`; a point beyond the end → `t = 1`.
- [ ] T011 [P] [US2] Write `tests/unit/planner/test_station_index.py` (pure), covering:
  - `build_station_index(rows)` sorts by `opis_id`;
  - `info` keeps `best_price` as an exact `Decimal` (e.g. `Decimal("3.00733333")`), plus `name`, `address`, `city`, `state` and `geo_source` as `GeoSource`;
  - the tree holds every station;
  - no rows → `StationDataMissing` with the exact message `station data not loaded: run python manage.py loaddata stations`;
  - no Django import (AST check).
- [ ] T012 [P] [US2] Write `tests/unit/planner/test_corridor.py` (pure; helpers from T003), covering:
  - **Straight line:** stations at known miles along a straight 200-mi route → `mile_marker` within 0.05 mi.
  - **Boundary:** with radius 10, a station at a true 9.99 mi off the route is included and one at 10.01 mi is excluded.
  - **On the route:** a station on the route → `off_route_miles == pytest.approx(0, abs=0.01)`.
  - **Sparse segment:** a 2-point 100-mi route still finds a station 3 mi off the midpoint.
  - **Latitude:** the same 9.5-mi offset is included both at 31°N (Texas) and at 48°N (Montana).
  - **Curve:** an arc route with radius 1 mi and a station on the arc → `off_route` within 0.01 mi and `mile_marker` within 0.05 mi of the true arc length (no corner-cutting).
  - **Rescale:** with `route.distance_miles` 2% longer than the geometry, the station at the end → `mile_marker == pytest.approx(distance_miles, abs=0.05)`.
  - **Rescale warning:** a 10% mismatch logs a WARNING (caplog) and still returns candidates; a 2% mismatch logs nothing.
  - **Loop:** a route passing a station twice lists it once, at the nearer pass. On equal distance it takes the earlier mile.
  - **Ordering:** two stations at the same mile are ordered by `opis_id`; two calls return identical lists.
  - **Fields:** `price` is the station's exact `Decimal`; no station nearby → `[]`; `corridor_miles` of 0.5 or 26 → `ValueError`.
- [ ] T013 [P] [US2] Write `tests/integration/test_index_loader.py` (pytest-django), covering:
  - after `loaddata tests/fixtures/stations_sample.json`, `get_station_index()` has 3 stations with exact prices;
  - a second call makes **0** queries (`django_assert_num_queries(0)`) and `cache_info().misses == 1`;
  - an empty DB → `StationDataMissing` with the `loaddata` hint, and a later call after `loaddata` succeeds (the exception is not cached);
  - a DB error on read (monkeypatch the query to raise `OperationalError("no such table: stations_fuelstation")`) → `StationDataMissing`. Its detail includes the original message, and a WARNING with that message is logged (caplog);
  - `cache_clear()` in an autouse fixture so tests are isolated.

### Implementation for User Story 2

- [ ] T014 [P] [US2] Implement `planner/geometry.py` (numpy; no Django): `haversine_miles`, `densify`, `cumulative_miles`, `to_unit_vectors`, `chord_for_miles`, `arc_miles`, and `project_onto_segment` (local equirectangular frame, `M = π·3958.8/180`). Run T010 green.
- [ ] T015 [P] [US2] Implement `planner/station_index.py`:
  - `StationInfo` (frozen dataclass), `StationIndex` (`opis_ids`, `lat`, `lng`, `vectors`, `tree`, `info`), `StationDataMissing`, and `build_station_index(rows)`;
  - rows are sorted by `opis_id`;
  - a `cKDTree` on the unit vectors;
  - no Django import.

  Run T011 green.
- [ ] T016 [US2] Implement `planner/corridor.py` (depends on T014, T015). Define `Candidate(opis_id, mile_marker, off_route_miles, price)` and `find_candidates(route, index, corridor_miles)`:
  - **Radius:** check 1 ≤ r ≤ 25, else `ValueError`.
  - **Densify:** `s = min(1, r/2)`, then `densify`.
  - **Rescale:** `k = route.distance_miles / cum[-1]`. If `k` is outside 0.95–1.05, `logging.getLogger(__name__).warning(...)`.
  - **Gather:** `index.tree.query_ball_point(unit_vectors(dense), chord(r + s/2))`.
  - **Measure:** for each candidate, take the nearest densified point (ties → lowest index), project onto its adjacent segments, and keep the smallest `off`, with ties going to the smaller mile.
  - **Include and sort:** include if `off <= r`; sort by `(mile_marker, opis_id)`.

  Run T012 green.
- [ ] T017 [US2] Implement `stations/services/index_loader.py`. `get_station_index()` is wrapped in `functools.lru_cache(maxsize=1)`:
  - reads `FuelStation.objects.order_by("opis_id").values_list("opis_id", "lat", "lng", "best_price", "name", "address", "city", "state", "geo_source")` once;
  - builds with `build_station_index`;
  - maps empty data to `StationDataMissing`;
  - maps `OperationalError`/`ProgrammingError` to `StationDataMissing`: it logs the original error at WARNING, and includes the original message in the exception detail;
  - is never called from `AppConfig.ready()`.

  Run T013 green.
- [ ] T018 [US2] Run `python -m pytest tests/unit/routing tests/unit/planner tests/integration/test_index_loader.py`. Fix until green.

**Checkpoint**: US1 and US2 both work offline.

---

## Phase 5: Polish & Cross-Cutting Concerns

- [ ] T019 Run quickstart §2, one real routing call (Dallas → Chicago). Expect about 966 mi and several thousand points. Note the result for the README.
- [ ] T020 Run quickstart §3–§4:
  - candidates on the real route with the real index (a few hundred, rising mile markers, `Decimal` prices);
  - time `find_candidates` on a synthetic 3,000-mile route against the real index (target well under 100 ms).

  Note the figures and the machine.
- [ ] T021 [P] Update `README.md`:
  - the status (002 done);
  - the real-call result (distance, points, time);
  - the measured `find_candidates` timing and machine (SC-004);
  - in "How it works", one sentence that routing failures are never retried, and that the list of reasons is in the 002 contract.
- [ ] T022 [P] Sync `docs/implementation-plan.md` Feature 002 if anything changed during implementation (module names, test list), and tick its "Done when".
- [ ] T023 Quality gate:
  - `python -m pytest --cov=planner --cov=routing --cov=stations --cov-report=term-missing` → ≥ 90% on `planner/` and `routing/`;
  - `ruff check .` and `ruff format --check .` (this also formats Python blocks inside Markdown);
  - `python manage.py check`.
- [ ] T024 Run the full quickstart.md validation (§1–§4) and confirm no test made a network call (respx asserts all requests are mocked).

---

## Dependencies & Execution Order

- **Phase 1 → Phase 2** (`routing/base.py`) **→ US1 and US2** (they can run in parallel) **→ Phase 5.**
- **US1:** T006/T007 before T008/T009; T009 depends on T008.
- **US2:** T010–T013 before T014–T017; T016 depends on T014 and T015; T017 depends on T015.
- **US2 uses `Route`** from Phase 2 only, not the OSRM provider. Its tests build routes synthetically.

### Parallel Opportunities

- **Setup:** T002 and T003.
- **US1 tests:** T006 and T007.
- **US2 tests:** T010, T011, T012 and T013, in different files.
- **US2 code:** T014 and T015.
- **Across stories:** US1 and US2 after Phase 2.
- **Polish:** T021 and T022.

---

## Parallel Example: User Story 2

```bash
# Tests first, together:
Task: "Write tests/unit/planner/test_geometry.py (T010)"
Task: "Write tests/unit/planner/test_station_index.py (T011)"
Task: "Write tests/unit/planner/test_corridor.py (T012)"
Task: "Write tests/integration/test_index_loader.py (T013)"

# Then the two independent pure modules:
Task: "Implement planner/geometry.py (T014)"
Task: "Implement planner/station_index.py (T015)"
```

---

## Implementation Strategy

1. Phase 1 + Phase 2: the fixture, the helpers and the shared types.
2. **MVP: US1.** The routing call with all failure modes is the base of every later feature. Commit as `feat(routing): OSRM provider with failure mapping`.
3. US2: geometry, then the index, then the corridor, then the loader. Commit as `feat(planner): corridor search and station index`.
4. Phase 5: the real call, timings, README and the quality gate. Commit as `docs: feature 002 results`.

## Notes

- `routing/base.py`, `routing/osrm.py` and all of `planner/` MUST NOT import Django (constitution III). Only `routing/factory.py` and `stations/services/index_loader.py` touch Django.
- Fixed value sets are enums (`RoutingFailure`; `GeoSource` reused). Application logic that needs Django lives in a service (`index_loader`).
- No retries anywhere in routing. Every routing test asserts exactly one call.
- Never assert timings in automated tests (SC-004 is measured by hand).
