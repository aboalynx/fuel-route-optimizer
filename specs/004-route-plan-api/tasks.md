---

description: "Task list for Feature 004: Route Plan API"
---

# Tasks: Route Plan API

**Input**: Design documents from `specs/004-route-plan-api/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/route_plan_api.md, quickstart.md

**Tests**: Required (constitution IV: test-first, offline).

- Each test file is written first and run to show it failing before its code exists. That output is the test-first record.
- No test touches the network: respx mocks OSRM with `tests/fixtures/osrm_dallas_chicago.json` (or a per-test response), and respx's default `assert_all_mocked` blocks anything else.
- Pure modules (`planner/*`, `routing/cached.py`, `api/enums.py`) get an AST "no Django import" test, like `tests/unit/stations/test_enums.py`.

**Organization**: by user story in priority order: US1 (P1, the endpoint), US2 (P1, cache), US3 (P2, errors), US4 (P2, map page), US6 (P2, minimum saving per stop), US5 (P3, optional GET). Location resolution and the error plumbing are foundational because every story needs them.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on unfinished tasks)
- **[Story]**: US1–US6 from spec.md
- Paths are repo-relative

---

## Phase 1: Setup

- [X] T001 Update `config/settings.py` (and document new keys in `.env.example` as comments):
  - `REST_FRAMEWORK = {"COERCE_DECIMAL_TO_STRING": False, "DEFAULT_AUTHENTICATION_CLASSES": [], "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"], "UNAUTHENTICATED_USER": None}` (the `EXCEPTION_HANDLER` key is added in T008, together with its module);
  - `CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "routes", "OPTIONS": {"MAX_ENTRIES": 500}}}`;
  - `ROUTE_CACHE_TTL_SECONDS = env.int("ROUTE_CACHE_TTL_SECONDS", default=86400)`, `ROUTING_RETRY_AFTER_SECONDS = env.int("ROUTING_RETRY_AFTER_SECONDS", default=30)`, `PLACES_INDEX_FILE = BASE_DIR / "data" / "places" / "us_places.csv.gz"`.
  - Run `python manage.py check`.
- [X] T002 [P] Create the empty packages `api/services/__init__.py`, `tests/unit/api/__init__.py`, `tests/integration/api/__init__.py`.
- [X] T003 [P] Create `tests/fixtures/stations_route_plan.json` (Django fixture of `stations.fuelstation`, same fields as `tests/fixtures/stations_sample.json`: `name`, `address`, `city`, `state`, `lat`, `lng`, `geo_source` `"city_centroid"`, `match_score` null, `best_price` as an 8-dp string). Place stations **exactly on points of** `tests/fixtures/osrm_dallas_chicago.json`'s geometry (50 `[lng, lat]` points), so they are 0 mi off the route:
  - pk 101 at geometry index 8, price `"3.10000000"`; pk 102 at index 16, `"2.95000000"`; pk 103 at index 24, `"3.25000000"`; pk 104 at index 36, `"2.90000000"`; pk 105 at index 20 moved 30 mi east (`lng + 30 / (69.17 × cos(lat))`), `"1.00000000"` (outside the 10-mi corridor, must never be a candidate).
  - Generate the coordinates with a one-off script in the scratchpad and commit only the JSON. Note the chosen geometry indexes in the docstring of `tests/integration/api/conftest.py` (T004).
- [X] T004 Create `tests/integration/api/conftest.py`:
  - autouse fixture: `django.core.cache.cache.clear()`, `get_station_index.cache_clear()`, `get_place_index.cache_clear()` before and after each test;
  - `route_stations` fixture: `call_command("loaddata", "tests/fixtures/stations_route_plan.json")`;
  - `osrm` fixture: a respx router mocking `GET {OSRM_BASE_URL}/route/v1/driving/...` with the recorded fixture (returns the route so tests can read `.call_count`);
  - `post(client, body)` helper: `client.post("/api/v1/route-plan/", body, content_type="application/json")`.
  - Docstring note: the recorded fixture keeps ~50 of the real route's points, so its geometry is shorter than its distance and `find_candidates` logs its mile-marker scaling WARNING on every API test. This is expected: one test in T012 asserts it once with `caplog`; all other API tests ignore it.

---

## Phase 2: Foundational (blocking)

**Purpose**: location resolution, the place index, the error codes and the error body, used by every story.

- [X] T005 [P] Write the failing test `tests/unit/planner/test_locations.py` (pure). Build a tiny place file in `tmp_path` with the same header as `data/places/us_places.csv.gz` (`normalised_name,display_name,state,lat,lng,population`; gzip) holding Dallas TX, Chicago IL, De Forest WI (normalised `de forest`), South Coffeyville OK. Cover:
  - `resolve_name("Dallas, TX")` and `"dallas, tx"` and `"  Dallas ,  TX "` → Dallas's coordinates, `place_name == "Dallas, TX"`;
  - `"DeForest, WI"` resolves through the compact key; `"S Coffeyville, OK"` too;
  - `"Dallas, Texas"` → `LocationNotFound` whose message contains `2-letter state code`;
  - `"Dallas"` (no comma) → `LocationNotFound` with the same hint;
  - `"Toronto, ON"`, `"San Juan, PR"` → `LocationOutsideUS` ("only the 50 states and DC are supported");
  - `"Springfield, XX"` → `LocationNotFound` ("unknown state code 'XX'");
  - `"Atlantis, TX"` → `LocationNotFound` naming the input;
  - `resolve_point(32.78, -96.80)` → inside (Dallas within 25 mi), `query == "32.78,-96.8"`, coordinates echoed unchanged, `place_name == "Dallas, TX"` (the nearest place); a point 30 mi from every place → `LocationOutsideUS`;
  - `load_place_index` on an empty, missing or unreadable (not gzip) file → `PlaceDataMissing` with the message "place data missing: data/places/us_places.csv.gz (restore it from git or rebuild with python manage.py build_station_data)" (the path in the message is the configured one);
  - `LocationNotFound` / `LocationOutsideUS` have `field is None` from the resolver;
  - `planner/locations.py` imports no Django (AST).
- [X] T006 [P] Write the failing test `tests/unit/api/test_enums.py`: `ErrorCode` values are exactly `invalid_input`, `location_not_found`, `location_outside_us`, `same_location`, `infeasible_route`, `routing_unavailable`, `station_data_missing`, `place_data_missing`, `internal_error`; `api/enums.py` imports no Django (AST).
- [X] T007 Implement `planner/locations.py` per research R2 and data-model.md (`Place`, `PlaceIndex`, `ResolvedLocation`, `LocationNotFound`, `LocationOutsideUS`, `PlaceDataMissing`, `load_place_index(path)`, `resolve_name(index, text)`, `resolve_point(index, lat, lng)`), reusing `stations.pipeline.geonames.normalise_place_name` / `compact_place_name` and `planner.geometry.to_unit_vectors` / `chord_for_miles`. Implement `api/enums.py` (`ErrorCode` `StrEnum`). Run T005 and T006 green.
- [X] T008 Implement `api/services/places.py` (`get_place_index()` with `functools.lru_cache(maxsize=1)`, reading `settings.PLACES_INDEX_FILE`; never called at import or in `AppConfig.ready()`) and `api/exceptions.py`, then add `"EXCEPTION_HANDLER": "api.exceptions.error_body_exception_handler"` to `REST_FRAMEWORK` in `config/settings.py` and run `python manage.py check`:
  - `error_response(code: ErrorCode, message: str, details: dict | None, status: int, headers=None) -> Response` building `{"error": {"code", "message", "details"}}`;
  - `error_body_exception_handler(exc, context)`: DRF's `ParseError`/`ValidationError`/`UnsupportedMediaType` → 400 `invalid_input` with `details = {"fields": exc.detail}` (or the parse message); other exceptions → DRF's default handler.

**Checkpoint**: locations resolve offline; errors have one shape.

---

## Phase 3: User Story 1 - Plan a trip through the API (Priority: P1) 🎯 MVP

**Goal**: `POST /api/v1/route-plan/` returns the full 200 response with exactly one routing call.

**Independent Test**: `tests/integration/api/test_route_plan_api.py` passes with respx and the route-plan fixture (SC-001 first part, SC-003).

### Tests for User Story 1 ⚠️ (write first, show failing)

- [X] T009 [P] [US1] Write `tests/unit/planner/test_route_output.py` (pure): `thin_line` keeps ≤ `max_points + 1` points, always the first and last, unchanged when already short; `point_at_mile(route, 0)` is the first point, at `route.distance_miles` the last, halfway along a 2-point straight route the midpoint (miles rescaled to `distance_miles`); `route_geojson` returns a `FeatureCollection` with one `LineString` (`properties.kind == "route"`, coordinates `[lng, lat]`) and one `Point` per stop (`kind == "fuel_stop"`, `sequence` from 1, `opis_id`, `name`, `price_usd_per_gallon`, `gallons`, `cost_usd`); no Django import (AST).
- [X] T010 [P] [US1] Write `tests/unit/api/test_serializers.py`: `start`/`finish` accept `"Dallas, TX"` or `{"lat", "lng"}`; reject `{"lat": 200, ...}`, `{"lat": "x"}`, `""`, a 101-char string, a list; numeric fields parse to `Decimal` (`"start_fuel_gallons": 20.5` → `Decimal("20.5")`, never via float repr noise); ranges: `corridor_miles` 1..25, `reserve_gallons` 0..25, `min_saving_per_stop_usd` 0..100, `start_fuel_gallons` ≥ 0 (capacity checked by the optimizer); unknown field `"min_saving_usd"` → error naming it; defaults: `corridor_miles` = `settings.CORRIDOR_MILES`, reserve 0, min saving 0, start fuel `None`.
- [X] T011 [P] [US1] Write `tests/unit/api/test_presenters.py` (build a `RoutePlanResult` by hand): precision per the contract (money 2 dp, gallons 4 dp, price exact, miles 3 dp); `summary.total_fuel_cost_usd == sum(stop.cost_usd)`; for every stop `abs(gallons × price_usd_per_gallon − cost_usd) ≤ Decimal("0.005")`; `fuel_stops[].sequence` from 1 in route order; `summary.assumptions` echoes all inputs; `summary.fuel_left_gallons` present (4 dp); `start.name == "Dallas, TX"` for a name input and the nearest place's name for coordinates; `meta` fields present.
- [X] T012 [US1] Write `tests/integration/api/test_route_plan_api.py` (fixtures from T004), covering:
  - `"Dallas, TX"` → `"Chicago, IL"`: 200, the top-level keys `start, finish, summary, fuel_stops, map, meta`; `meta.routing_calls == 1`, `cached is False`, `osrm.call_count == 1`; `meta.candidate_stations_considered == 4` (pk 105 excluded); stops in route order with all contract fields; money check as in T011;
  - the same with `{"lat": 32.78, "lng": -96.80}` inputs: 200, `start.query == "32.78,-96.8"`, `start.name == "Dallas, TX"`;
  - **the expected scaling warning, asserted once:** with `caplog` on `planner.corridor`, the happy-path request logs exactly one WARNING about the provider distance ÷ geometry length (the trimmed fixture); no other API test checks it;
  - optional values echoed in `summary.assumptions`, and defaults when omitted (`start_fuel_gallons` 50, `corridor_miles` 10, `reserve_gallons` 0, `min_saving_per_stop_usd` 0);
  - a trip shorter than 500 mi (respx returns a 2-point 300-mi route) → 200, `fuel_stops == []`, `total_fuel_cost_usd == 0`;
  - two identical requests → identical `summary` and `fuel_stops`;
  - after the first request, a second makes no DB query for stations (`django_assert_num_queries(0)` around the second call).

### Implementation for User Story 1

- [X] T013 [US1] Implement `planner/route_output.py` (`thin_line(points, max_points=5000)`, `point_at_mile(route, mile)`, `route_geojson(points, stops)`) per research R7. Run T009 green.
- [X] T014 [US1] Implement `api/serializers.py`: `LocationField` (string or `{lat, lng}` → `str` or `(float, float)`), `RoutePlanRequestSerializer` with `DecimalField`s (`max_digits=10`, `decimal_places=4` for gallons/miles, `2` for USD) and the ranges from data-model.md, rejecting unknown fields in `validate`. Run T010 green.
- [X] T015 [US1] Implement `api/services/route_plan.py`: `RoutePlanInput`, `RoutePlanResult`, `plan_route(inp, *, provider=None)`:
  - resolve both locations with `get_place_index()` (timed as `resolve`); on `LocationNotFound`/`LocationOutsideUS` set `exc.field` to `"start"` or `"finish"` and re-raise;
  - check the vehicle-dependent request values **before** routing (capacity = `VEHICLE_MAX_RANGE_MILES / VEHICLE_MPG`): start fuel ≤ capacity, reserve < capacity, start fuel ≥ reserve, else `InvalidPlanInput(field, message)` (research R8);
  - route with `provider_from_settings()` (timed as `routing`; `routing_calls = 1`, `cached = False` for now);
  - `find_candidates(route, get_station_index(), float(inp.corridor_miles))` (timed as `candidates`);
  - convert to `PlanStation` per research R5 (quantize 0.001, clamp, **re-sort by `(mile_marker, opis_id)`**), vehicle from settings via `Decimal(str(...))`;
  - `plan_refuelling(...)` wrapped as `FewerStopsResult(plan, cheapest=plan, stops_dropped=0)` (US6 replaces this), timed as `optimize`; `total` timing.
- [X] T016 [US1] Implement `api/presenters.py` (`present(result) -> dict` per the contract, using `thin_line` and `route_geojson`) and `api/views.py` `RoutePlanView(APIView).post` (serializer → `plan_route` → `present` → 200; domain errors mapped in a single table, initially `InvalidPlanInput` → 400 `invalid_input` with `details.field`; a final catch-all → 500 `internal_error`, message "internal error", `logger.exception(...)` with the traceback, no exception text in the body), `api/urls.py` (`api/v1/route-plan/`), and include it in `config/urls.py`. Run T011 and T012 green.

**Checkpoint**: the MVP endpoint works offline end to end.

---

## Phase 4: User Story 2 - Repeat requests without calling the routing service again (Priority: P1)

**Goal**: a repeated route within 24 h makes 0 calls and returns an identical plan (FR-004, SC-001).

**Independent Test**: `tests/unit/routing/test_cached.py` and `tests/integration/api/test_cache.py` pass.

### Tests for User Story 2 ⚠️

- [ ] T017 [P] [US2] Write `tests/unit/routing/test_cached.py` (pure, a dict-backed fake cache with `get`/`set(key, value, timeout)` and a fake provider counting calls): miss → 1 call, `(route, False)`, value stored with `timeout == ttl_seconds`; hit → 0 calls, `(route, True)`; a provider raising `RoutingUnavailable` → re-raised, nothing stored, next call tries again; `cache_key` equal for `32.780049999` vs `32.78004` (both round to `32.7800`) and different for `32.78005001`; `-0.00001` and `0.0` share a key; key contains the provider name; no Django import (AST).
- [ ] T018 [P] [US2] Write `tests/integration/api/test_cache.py`: two identical requests → second has `routing_calls == 0`, `cached is True`, `osrm.call_count == 1`, identical `summary`/`fuel_stops`; same start/finish with a different `start_fuel_gallons`, `corridor_miles`, `reserve_gallons` or `min_saving_per_stop_usd` → 0 calls and a plan for the new values; coordinates differing beyond the 4th decimal share the route; a first request answered 503 (respx timeout) followed by the same request with OSRM back → `routing_calls == 1` (failure not cached).

### Implementation for User Story 2

- [ ] T019 [US2] Implement `routing/cached.py` (`CachedRoutingProvider`, `cache_key`) per research R3. Run T017 green.
- [ ] T020 [US2] In `api/services/route_plan.py`, wrap the provider: `CachedRoutingProvider(provider_from_settings(), django.core.cache.cache, settings.ROUTE_CACHE_TTL_SECONDS)`; set `routing_calls = 0 if cached else 1` and `cached`. Run T018 and all US1 tests green.

**Checkpoint**: US1 + US2 are the shippable core.

---

## Phase 5: User Story 3 - Clear errors for every failure (Priority: P2)

**Goal**: every failure returns its documented status, code, message and details (FR-008–FR-010, FR-016, SC-002).

**Independent Test**: `tests/integration/api/test_errors.py` passes.

### Tests for User Story 3 ⚠️

- [ ] T021 [US3] Write `tests/integration/api/test_errors.py`, one test per row (status, `error.code`, message substring, `details` keys):
  - malformed JSON body; missing `finish`; `{"lat": 200, "lng": 0}`; unknown field → 400 `invalid_input` naming the field;
  - `corridor_miles: 0.5` and `26`; `reserve_gallons: 26`; `min_saving_per_stop_usd: 101` → 400 `invalid_input` (serializer ranges);
  - `"Dallas, Texas"` as `start` → 400 `location_not_found`, message contains `2-letter state code`, `details.field == "start"`; `"Atlantis, TX"` as `finish` → 400 `location_not_found`, `details.field == "finish"`;
  - `{"lat": 19.43, "lng": -99.13}` (Mexico City) and `"Toronto, ON"` → 400 `location_outside_us`;
  - **same location:** `"Dallas, TX"` → `"dallas, tx"` → 400 `same_location`, `osrm.call_count == 0`; lat `32.78004999` vs `32.78005001` (same lng) with respx returning a route of `distance: 0.5` m and 2 identical points → 400 `same_location` (the guard), never 500; two points 1 mile apart with a 1-mile 2-point route → 200 with 0 stops;
  - **422 gap:** load only stations pk 101 (respx full route) → `infeasible_route`, `details.reason == "station gap"`, `gap_start_mile`, `gap_end_mile`, `gap_start`/`gap_end` `{lat, lng}` on the route, `usable_range_miles == 500`;
  - **422 start fuel:** `start_fuel_gallons: 0` → `infeasible_route`, `reason == "start fuel insufficient"`, `start_fuel_gallons`, `reserve_gallons`, `gallons_short` present;
  - **503:** respx `httpx.ReadTimeout` → `routing_unavailable`, `details.reason == "timed out"`, header `Retry-After: 30`; respx 429 with `Retry-After: 2` → header `2`;
  - **station data missing:** no stations loaded → 503 `station_data_missing`, message contains `loaddata`;
  - **place data missing:** `settings.PLACES_INDEX_FILE` pointed at a missing file, and at a non-gzip file → 503 `place_data_missing`, message exactly "place data missing: data/places/us_places.csv.gz (restore it from git or rebuild with python manage.py build_station_data)";
  - **vehicle-dependent values:** `start_fuel_gallons: 60` and `reserve_gallons: 5` with `start_fuel_gallons: 4` → 400 `invalid_input` with `details.field` = `start_fuel_gallons`;
  - **internal error is not bad input:** monkeypatch the service's candidate conversion to return stations out of order (so the optimizer raises `ValueError`) → 500 `internal_error` with message "internal error" (test client with `raise_request_exception=False`), never 400 `invalid_input`; the body contains no exception text (no `ValueError`, no `sorted`); `caplog` shows the logged traceback.

### Implementation for User Story 3

- [ ] T022 [US3] In `api/services/route_plan.py`, add `SameLocation` and both checks (research R4): rounded coordinates equal → raise before routing; `route.distance_miles < 0.01` or `cumulative_miles(points)[-1] < 0.01` → raise before `find_candidates`. Catch `InfeasibleRoute` to attach `gap_start`/`gap_end` coordinates via `point_at_mile` (re-raise inside a small `InfeasibleRouteAt` wrapper or return them on the result of the exception; keep the optimizer unchanged).
- [ ] T023 [US3] In `api/views.py`, complete the error table (research R8): `LocationNotFound`, `LocationOutsideUS`, `SameLocation` → 400; `InfeasibleRoute` → 422 with the details listed in the contract (Decimal values as numbers); `RoutingUnavailable` → 503 with `Retry-After` (`exc.retry_after_seconds` or `settings.ROUTING_RETRY_AFTER_SECONDS`); `StationDataMissing` → 503 `station_data_missing`; `PlaceDataMissing` → 503 `place_data_missing`; `details.field` for the location errors and `InvalidPlanInput`; the catch-all from T016 stays last (500 `internal_error`). Run T021 green.

**Checkpoint**: every failure is a documented JSON error; the only 500 in the tests is the deliberate internal-error case.

---

## Phase 6: User Story 4 - See the plan on a map (Priority: P2)

**Goal**: a page at `/` shows the route, numbered stops and a summary (FR-012).

**Independent Test**: `tests/integration/api/test_map_page.py` passes; Dallas → Chicago and New York → Los Angeles render by hand (T036).

- [ ] T024 [P] [US4] Write `tests/integration/api/test_map_page.py`: `GET /` → 200, HTML containing a form with `start` and `finish` inputs, the Leaflet script URL pinned to `leaflet/1.9.4`, and the API path `/api/v1/route-plan/`; no `{{` left unrendered.
- [ ] T025 [US4] Implement `web/views.py` `MapView(TemplateView)` with `template_name = "web/map.html"`, `web/urls.py`, the include in `config/urls.py`, and `web/templates/web/map.html` per research R9: Leaflet 1.9.4 CSS/JS from cdnjs with SRI; OSM tile layer with attribution; form (start, finish, start fuel, radius, reserve, min saving per stop); `fetch` POST with JSON; `L.geoJSON` for the route; numbered `divIcon` markers with popups (name, price, gallons, cost); summary panel (distance, total cost, stops, routing calls, total time from `meta.timings_ms.total`); an error box showing `error.message`; inline CSS/JS; works at phone width. Run T024 green.

---

## Phase 7: User Story 6 - Skip stops that barely save money (Priority: P2)

**Goal**: optional `min_saving_per_stop_usd` (default 0 = off) drops stops that save less than it (FR-015, SC-007).

**Independent Test**: `tests/unit/planner/test_fewer_stops.py` and the min-saving cases in `tests/integration/api/test_route_plan_api.py` pass.

### Tests for User Story 6 ⚠️

- [ ] T026 [P] [US6] Write `tests/unit/planner/test_fewer_stops.py` (pure, 10 mpg, 500 mi):
  - `min_saving_usd = 0` → `plan == cheapest == plan_refuelling(...)`, `stops_dropped == 0`, extra `0.00` (several inputs from `tests/unit/planner/test_optimizer.py`);
  - a hand-made trip whose cheapest plan has a stop saving $0.10 → with 5 that stop is dropped, `stops_dropped == 1`, `extra_cost_vs_cheapest_usd ≤ 0.10`, and gallons move to another stop;
  - **invariant** on several trips and thresholds (0.5, 5, 50): for every stop in `plan`, re-planning over the other stops of `plan` is infeasible or costs ≥ threshold more;
  - a stop the trip needs (the only station within 500 mi of another fuel point) is never dropped, even at the maximum threshold of 100;
  - tie order: two stops with equal saving → the earlier mile is dropped first; equal mile → lower `opis_id`;
  - validation: `-1`, `101` → `ValueError`; `5.0` → `TypeError`;
  - `InfeasibleRoute` from the cheapest plan propagates unchanged;
  - deterministic: two calls equal; no Django import (AST).
- [ ] T027 [P] [US6] Add to `tests/integration/api/test_route_plan_api.py`: with `min_saving_per_stop_usd: 5` on the route-plan fixture, `summary.stops_dropped` and `summary.extra_cost_vs_cheapest_usd` are present and consistent with a request without it (`total_fuel_cost_usd` difference equals `extra_cost_vs_cheapest_usd`), and `summary.assumptions.min_saving_per_stop_usd == 5`; without it, both are 0.

### Implementation for User Story 6

- [ ] T028 [US6] Implement `planner/fewer_stops.py` (`FewerStopsResult`, `plan_with_min_saving`) per research R6. Run T026 green.
- [ ] T029 [US6] In `api/services/route_plan.py`, replace the `plan_refuelling` wrapper with `plan_with_min_saving(..., min_saving_usd=inp.min_saving_per_stop_usd)`; the presenter adds `stops_dropped` and `extra_cost_vs_cheapest_usd` (already in the contract). Run T027 and all API tests green.

---

## Phase 8: User Story 5 - Plan through a GET request (Priority: P3, optional)

**Goal**: the same request as query parameters (FR-013). **Drop this phase first if time is short.**

- [ ] T030 [P] [US5] Write `tests/integration/api/test_get.py`: `GET /api/v1/route-plan/?start=Dallas,%20TX&finish=Chicago,%20IL` → 200 with the same `summary` and `fuel_stops` as the POST; `start=32.78,-96.80` coordinates form; a bad parameter → 400 `invalid_input`.
- [ ] T031 [US5] Add `RoutePlanView.get`: map query parameters to the serializer input (`"lat,lng"` strings → `{lat, lng}`), then the same path as `post`. Run T030 green.

---

## Phase 9: Polish & Cross-Cutting Concerns

- [ ] T032 Run quickstart §2–§4 by hand: one real Dallas → Chicago request (expect ~966 mi, 4 stops, $134.64, `routing_calls` 1), the repeat (`routing_calls` 0, identical plan), and `min_saving_per_stop_usd: 5` (2 stops, $134.81, `stops_dropped` 2, extra 0.17). Note the figures.
- [ ] T033 Time a first and a cached Dallas → Chicago request (quickstart §7, SC-004); note `meta.timings_ms` and wall clock with the machine.
- [ ] T034 [P] Create the Postman collection `postman/fuel_route_optimizer.postman_collection.json` (v2.1, `{{base_url}}` variable = `http://localhost:8000`): Dallas → Chicago (City, ST); the same with coordinates; the repeat (cached); **min saving per stop = 5** (description: "drops the 7¢ and 10¢ stops for 17¢ more"); `"Dallas, Texas"` (400); start fuel 0 (422); New York → Los Angeles.
- [ ] T035 [P] Update `README.md`: status (004 done); "Running the API" (`runserver`, open `/`); the API section from the contract (request fields incl. `reserve_gallons` and `min_saving_per_stop_usd`, response example, precision rule, error table incl. `station_data_missing`); assumptions (coordinates inside the USA within 25 mi of a place, 2-letter states, territories rejected, route cache 24 h per process and stores the route only, min saving per stop off by default and what 5 does on Dallas → Chicago, map line thinned to ~5,000 points); measured timings (T033); the Postman collection.
- [ ] T036 Check the map page by hand: Dallas, TX → Chicago, IL and New York, NY → Los Angeles, CA render with stops; an unknown city shows the error (spec US4 scenario 3 is checked only by hand, since the page has no JavaScript test setup by design); the page works at phone width.
- [ ] T037 [P] Sync `docs/implementation-plan.md` Feature 004 (service in `api/services/` not `planner/services/`, the new modules, the min-saving rule, the precision rule) and tick its "Done when"; add a short "Fewer stops" section to `docs/algorithms/refuelling-greedy.md` (the rule, why only the plan's own stops, the cascade measured in the prototype, the guarantee and its limit).
- [ ] T038 Quality gate: `python -m pytest --cov=planner --cov=routing --cov=api --cov=stations --cov-report=term-missing` (≥ 90% on `planner/`, `routing/` and `api/`; whole suite green); `ruff check .`; `ruff format --check .`; `python manage.py check`.
- [ ] T039 Run the full quickstart.md (§1–§7) and confirm no test made a network call. Then check SC-006 from a fresh clone in the scratchpad: follow the README setup exactly (venv, `pip install -r requirements-dev.txt`, `cp .env.example .env`, `migrate`, `loaddata stations`, `pytest`), start `runserver` and make one request; no API key, no build step.

---

## Dependencies & Execution Order

- **Phase 1 → Phase 2 → US1 → US2 → US3 → (US4, US6 in either order) → US5 (optional) → Polish.**
- **US1:** T009–T012 before T013–T016; T015 depends on T007/T008 and T013; T016 on T014/T015.
- **US2:** T017/T018 before T019/T020; T020 edits the service from T015.
- **US3:** T021 before T022/T023; both edit files from US1.
- **US4:** independent of US2/US3/US6 (only needs the endpoint).
- **US6:** T026/T027 before T028/T029; T029 edits the service and presenter.
- **US5:** after US1; optional.
- `api/services/route_plan.py`, `api/views.py` and `api/presenters.py` are edited by several stories: those tasks run sequentially.

### Parallel Opportunities

- **Setup:** T002, T003.
- **Foundational tests:** T005, T006.
- **US1 tests:** T009, T010, T011 (T012 after T004).
- **US2 tests:** T017, T018.
- **Pure modules across stories:** `planner/route_output.py` (T013), `routing/cached.py` (T019) and `planner/fewer_stops.py` (T028) touch different files and can be built in parallel once their tests exist.
- **US4** can be built alongside US3/US6.
- **Polish:** T034, T035, T037.

---

## Parallel Example: User Story 1

```bash
# Tests first, together:
Task: "Write tests/unit/planner/test_route_output.py (T009)"
Task: "Write tests/unit/api/test_serializers.py (T010)"
Task: "Write tests/unit/api/test_presenters.py (T011)"

# Then:
Task: "Implement planner/route_output.py (T013)"
Task: "Implement api/serializers.py (T014)"
```

---

## Implementation Strategy

1. Phases 1–2: settings, fixtures, locations, error plumbing. Commit as `feat(api): location resolution and error body`.
2. **MVP: US1 + US2** (both P1): the endpoint and the cache. Commit as `feat(api): route-plan endpoint` and `feat(routing): route cache`.
3. US3: errors and the same-location guard. Commit as `feat(api): documented errors`.
4. US4: map page. Commit as `feat(web): map page`.
5. US6: minimum saving per stop. Commit as `feat(planner): minimum saving per stop`.
6. US5 (optional): GET. Commit as `feat(api): GET form`.
7. Polish: real call, timings, Postman, README, docs, quality gate. Commit as `docs: feature 004 results`.

## Notes

- `planner/*`, `routing/cached.py` and `api/enums.py` MUST NOT import Django (constitution III).
- Every number entering the optimizer is a `Decimal`; request numbers are parsed straight to `Decimal` (constitution V).
- No bare error-code strings in code: use `ErrorCode` (constitution, technical constraints).
- Never assert timings in automated tests (SC-004 is by hand).
