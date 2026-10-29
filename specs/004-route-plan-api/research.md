# Research: Route Plan API (004)

Every decision below resolves the Technical Context; nothing is left as NEEDS CLARIFICATION. The
spec's clarifications (stop-saving default, output precision, same location) are inputs here. The
stop-saving default changed from 0 to 5 USD on 2026-10-30 (spec Clarifications); R6 below.

## R1. Layering: pure core, thin Django

- **Decision:** new pure modules hold all logic that does not need Django; one Django service
  composes them.
  - `planner/locations.py` (pure): load the committed place file, resolve `"City, ST"` and
    coordinates.
  - `planner/fewer_stops.py` (pure): the minimum-saving-per-stop rule on top of `plan_refuelling`.
  - `planner/route_output.py` (pure): thin the route line, find the point at a mile marker, build
    the GeoJSON.
  - `routing/cached.py` (pure): a caching wrapper around any `RoutingProvider`, given a cache
    object with `get`/`set` (Django's cache in production, a dict-backed fake in tests).
  - `api/services/route_plan.py` (Django service): reads settings, gets the station and place
    indexes, runs routing → guard → corridor → optimizer → fewer stops, times each step, and
    returns a plain result object.
  - `api/services/places.py` (Django service): `get_place_index()` with `lru_cache`, like
    `stations/services/index_loader.py`.
  - `api/views.py`, `api/serializers.py`, `api/presenters.py`: parse input, call the service, format
    output, map errors. `web/views.py` + template: the map page.
- **Rationale:** constitution III (pure core) and the services rule. Everything with a branch
  worth testing is testable without Django.
- **Alternatives considered:** `planner/services/route_plan.py` as in the implementation-plan input
  (but `planner/` is a pure package, not a Django app, and the service needs settings and the cache);
  logic in the view (violates "thin views").

## R2. Resolving locations

- **Decision:**
  - **`"City, ST"`:** split on the last comma; trim. The state must match `^[A-Za-z]{2}$`, else
    `location_not_found` with "use a 2-letter state code, e.g. 'Dallas, TX'". Upper-case it.
    - US territories and Canadian provinces/territories (`PR VI GU AS MP AB BC MB NB NL NS NT NU ON
      PE QC SK YT`) → `location_outside_us` ("only the 50 states and DC are supported").
    - Any other code not among the 51 in the place file → `location_not_found` ("unknown state
      code 'XX'").
    - The city is looked up by `(normalise_place_name(city), state)`, then by
      `(compact_place_name(city), state)` against a compact map built at load time. Both
      functions come from `stations/pipeline/geonames.py` (pure), the same rules the pipeline
      used, so every city a station was matched to also resolves.
    - Not found → `location_not_found` naming the input.
    - **Alias (found during implementation):** GeoNames' main name for New York is "New York
      City", and the place file keeps main names only, so `"New York, NY"` failed. An explicit
      `ALIASES` table maps `("new york", "NY")` → `"new york city"`. A general "append City" rule
      was rejected: it would silently resolve e.g. "Carson, NV" to Carson City.
  - **Coordinates:** validated as numbers in −90..90 / −180..180 (400 `invalid_input`
    otherwise). Inside the USA when the nearest place in the file is within 25 miles: a `cKDTree`
    on 3D unit vectors of the ~31,500 places, queried with the chord for 25 miles
    (`planner.geometry.chord_for_miles`). Else `location_outside_us`.
  - The resolved location keeps the original `query` (the string, or `"lat,lng"`), `lat`, `lng`,
    and a display name: the matched place for a city, the nearest place (from the 25-mile check)
    for coordinates.
- **Rationale:** reuses the pipeline's exact name rules and data (constitution VIII: no geocoding
  call); one KD-tree query is microseconds.
- **Alternatives considered:** fuzzy matching of user input (a typo would silently resolve to
  another town, worse than a clear 400); full state names (decided against in the Specify input).

## R3. Route cache

- **Decision:** `CachedRoutingProvider(provider, cache, ttl_seconds)` with
  `route(start, finish) -> tuple[Route, bool]` (route, cached?).
  - **Key:** `route:v1:{provider.name}:{lat1:.4f},{lng1:.4f};{lat2:.4f},{lng2:.4f}` from
    `round(x, 4)` (with `+ 0.0` so −0.0 and 0.0 share a key).
  - **Value:** the `Route` dataclass (picklable). Only successes are stored; a
    `RoutingUnavailable` propagates and nothing is written (spec US2 scenario 4).
  - **Backend:** Django's `LocMemCache` (`CACHES["default"]`, `MAX_ENTRIES` 500), TTL
    `ROUTE_CACHE_TTL_SECONDS` = 86,400. Tests clear it in an autouse fixture.
  - `routing_calls` in the response = 0 on a hit, 1 on a miss.
- **Rationale:** constitution VII (amended) allows exactly this; the plan is recomputed on every
  request, so a hit never changes the plan.
- **Alternatives considered:** caching the whole response (would freeze timings and ignore
  start fuel/radius/reserve/min-saving changes); Redis (infrastructure; future work).

## R4. Same location and the zero-length guard

- **Decision:** two checks in the service (spec FR-016).
  1. Before routing: the rounded coordinates (the cache key's 4 dp) are equal → `SameLocation`.
  2. After routing, before the corridor search: `route.distance_miles < 0.01` or the geometry
     length (`cumulative_miles(points)[-1]`) `< 0.01` → `SameLocation`.
- **Rationale:** check 2 catches points that round differently but snap to the same road point,
  and keeps `find_candidates` from dividing by a zero geometry length. The request never 500s.

## R5. Converting to the optimizer and back

- **Decision:**
  - Distance and mile markers: `Decimal(float(x)).quantize(Decimal("0.001"))`; markers clamped to
    the distance; then re-sorted by `(mile_marker, opis_id)` (003 research R5).
  - Vehicle: `Decimal(str(settings.VEHICLE_MPG))`, `Decimal(str(settings.VEHICLE_MAX_RANGE_MILES))`.
  - Request numbers (start fuel, reserve, min saving) are parsed straight to `Decimal` by the
    serializer (`DecimalField`), never through float.
- **Output precision** (spec clarification, D10): money `round_cents` (already done by the
  optimizer), gallons `quantize(Decimal("0.0001"), ROUND_HALF_UP)` (exact at 10 mpg), price exact
  as stored. Distances: `distance_miles`, `mile_marker`, `off_route_miles` to 3 dp; coordinates
  as given (lat/lng floats, up to 6 dp in the station data).
- **JSON numbers:** `REST_FRAMEWORK["COERCE_DECIMAL_TO_STRING"] = False`; DRF's JSON encoder
  writes a `Decimal` as a number. Trailing zeros are not kept in JSON (`129.30` is sent as
  `129.3`); tests compare numbers, not strings.

## R6. Minimum saving per stop

- **Decision:** `plan_with_min_saving(distance_miles, stations, *, min_saving_usd, **vehicle)
  -> FewerStopsResult(plan, cheapest, stops_dropped)` in `planner/fewer_stops.py`:
  1. `cheapest = plan_refuelling(...)` over all stations (raises `InfeasibleRoute` as before).
  2. If `min_saving_usd == 0`, return `cheapest` unchanged (the oracle-checked plan).
  - **Default (2026-10-30):** the API defaults to 5 USD (`DEFAULT_MIN_SAVING_PER_STOP_USD`);
    `cheapest` is always computed anyway, so `minimum_possible_cost_usd` costs no extra call.
  3. Otherwise `keep` = the stations of the current plan's stops. For each stop, re-plan over
     `keep` minus that station; skip it if infeasible; `saving = alt.total − current.total`.
     Take the smallest by `(saving, mile_marker, opis_id)`; if `saving < min_saving_usd`, adopt
     `alt`, set `keep` to `alt`'s stops, count one drop, repeat; else stop.
  - `extra_cost_vs_cheapest_usd = plan.total_cost_usd − cheapest.total_cost_usd`.
- **Rationale:** prototyped on the real Dallas → Chicago route (spec clarifications): dropping
  from all candidates cascades (+$34.98); dropping only the plan's own stops gives 2 stops for
  +$0.17 in 1.2 ms. Each round removes a stop, so it ends after at most (stops − 1) rounds.
- **Validation:** `0 ≤ min_saving_usd ≤ 100`, a `Decimal` (else `ValueError`/`TypeError`).

## R7. Response map and gap coordinates

- **Decision:**
  - **Line thinning:** keep every `ceil(n / 5000)`-th point plus the last point, so at most 5,001
    points; computed from the full route only after the plan is done (spec FR-011).
  - **GeoJSON:** a `FeatureCollection` with one `LineString` feature (`properties.kind = "route"`)
    and one `Point` per stop (`kind = "fuel_stop"`, `sequence`, `opis_id`, `name`,
    `price_usd_per_gallon`, `gallons`, `cost_usd`). Coordinates `[lng, lat]` (GeoJSON order).
  - **Point at a mile** (422 gap ends): walk the cumulative miles of the route (rescaled to the
    provider distance like the corridor) and interpolate linearly inside the segment.
- **Rationale:** a 3,000-mile route has ~30,000 points (~1 MB of JSON); 5,000 points keep the line
  smooth at map zoom levels and the response small.

## R8. Errors

- **Decision:** `ErrorCode` `StrEnum` in `api/enums.py` (Django-free): `INVALID_INPUT`,
  `LOCATION_NOT_FOUND`, `LOCATION_OUTSIDE_US`, `SAME_LOCATION`, `INFEASIBLE_ROUTE`,
  `ROUTING_UNAVAILABLE`, `STATION_DATA_MISSING`, `PLACE_DATA_MISSING`, `INTERNAL_ERROR`. One mapping table in `api/views.py`:

  | Exception | Status | Code |
  | --- | --- | --- |
  | serializer `ValidationError`; `InvalidPlanInput(field, message)` from the service (`details.field`) | 400 | `invalid_input` |
  | `LocationNotFound` | 400 | `location_not_found` |
  | `LocationOutsideUS` | 400 | `location_outside_us` |
  | `SameLocation` | 400 | `same_location` |
  | `InfeasibleRoute` | 422 | `infeasible_route` |
  | `RoutingUnavailable` | 503 + `Retry-After` | `routing_unavailable` |
  | `StationDataMissing` | 503 | `station_data_missing` |
  | `PlaceDataMissing` (file missing or unreadable) | 503 | `place_data_missing`, message "place data missing: data/places/us_places.csv.gz (restore it from git or rebuild with python manage.py build_station_data)" |
  | anything else (incl. `ValueError`/`TypeError` from the core) | 500 | `internal_error`, message "internal error"; `logger.exception(...)` logs the traceback; no exception text in the body |

  The service checks the request values that depend on the vehicle **before** calling the
  optimizer (start fuel ≤ capacity, reserve < capacity, start fuel ≥ reserve) and raises
  `InvalidPlanInput(field, message)`. So a `ValueError` from the optimizer can only mean a server bug
  (for example unsorted stations) and must not be reported to the client as bad input.
  `LocationNotFound` and `LocationOutsideUS` carry `field` (`"start"`/`"finish"`), set by the
  service, which the view puts in `details`.

  Body: `{"error": {"code", "message", "details"}}`. `Retry-After` = the provider's
  `retry_after_seconds` or `ROUTING_RETRY_AFTER_SECONDS` (30).
- **DRF settings:** no authentication classes (so no CSRF check on the anonymous JSON POST from
  the map page), `AllowAny`, JSON renderer plus the browsable API, `EXCEPTION_HANDLER` left default
  (the view catches the domain errors itself; DRF's own 400 for malformed JSON is reshaped by a
  small custom exception handler into the same body).

## R9. Map page

- **Decision:** `web/views.py` `MapView(TemplateView)` at `/`, template
  `web/templates/web/map.html`: Leaflet 1.9.4 from cdnjs (pinned, with SRI hash), OpenStreetMap
  tiles (attribution shown), a form (start, finish, optional start fuel, radius, reserve, min
  saving), `fetch()` POST to `/api/v1/route-plan/`, `L.geoJSON` for the line and numbered
  `divIcon` markers with popups, a summary panel, and an error box. Inline CSS/JS, no build step.
- **Rationale:** spec FR-012 and constitution VIII (no key, no build).

## R10. Timings

- **Decision:** `time.perf_counter()` around resolve, routing, candidates, optimize (includes the
  fewer-stops rule) and total; reported as whole milliseconds (`round`). The first request in a
  process also pays the station and place index builds (~0.1 s and ~0.05 s), reported inside
  `candidates` and `resolve`.
- **Targets (SC-004, by hand):** cached Dallas → Chicago under 100 ms; first request = routing time
  + under 100 ms.
