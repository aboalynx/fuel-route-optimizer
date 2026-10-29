# Implementation Plan: Route Plan API

**Branch**: `004-route-plan-api` | **Date**: 2026-10-29 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/004-route-plan-api/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

This feature exposes the planner: `POST /api/v1/route-plan/` and a Leaflet map page at `/`.

- **Request path:** validate → resolve `"City, ST"` or coordinates locally (committed place file,
  KD-tree for "inside the USA") → same-location check → route from the cache or **one** OSRM call
  → zero-length guard → corridor search (002) → optimizer (003) → optional minimum-saving rule →
  response with exact money, GeoJSON and per-step timings (research R1–R5, R10).
- **New pure modules:** `planner/locations.py`, `planner/fewer_stops.py`,
  `planner/route_output.py`, `routing/cached.py`. Django code stays thin: one service
  (`api/services/route_plan.py`), a place-index loader, serializers, a presenter, one view, one
  template.
- **Clarified behaviour:** `min_saving_per_stop_usd` defaults to 0 so the default response is the
  oracle-checked optimum (R6); price exact, gallons 4 dp, money 2 dp (R5); same location by 4-dp
  rounding plus a < 0.01 mi guard (R4).

## Technical Context

**Language/Version**: Python 3.15 (venv 3.15.2). Supported: 3.13–3.14 officially (Django 6.1.2), also CI-tested on 3.15.

**Primary Dependencies**: Django 6.1.2, Django REST Framework 3.18.3, numpy/scipy (`cKDTree`), httpx. All pinned already; no new runtime dependency. Leaflet 1.9.4 from cdnjs in the page (pinned, SRI).

**Storage**: none new. Reads `FuelStation` once per process (002), `data/places/us_places.csv.gz` once per process, and Django's in-process `LocMemCache` for routes (24 h).

**Testing**: pytest, pytest-django (`client`, `settings`, `django_assert_num_queries`), respx (OSRM mocked, the recorded Dallas → Chicago fixture), a new route-plan station fixture placed on the recorded route.

**Target Platform**: developer laptop and the CI matrix (3.13, 3.14, 3.15).

**Project Type**: web service (Django + DRF) with one server-rendered page.

**Performance Goals**: cached Dallas → Chicago under 100 ms; first request = routing time + under 100 ms of local work (SC-004, by hand).

**Constraints**: at most 1 routing call per request (0 on a cache hit); no DB query per request after the indexes are built; exact `Decimal` money; deterministic plans; no API key and no frontend build.

**Scale/Scope**: one endpoint (+ optional GET), one page; ~6,600 stations, ~31,500 places; responses up to ~5,000 line points.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle / rule | Check | Status |
| --- | --- | --- |
| I. Deterministic Results | The plan depends only on inputs and data; the cache stores the route only and the plan is recomputed; the fewer-stops rule has a fixed tie order (R6) | Pass |
| II. Single External Routing Call | `CachedRoutingProvider` makes 0 or 1 call; failures are not cached or retried (R3); tests assert the call count | Pass |
| III. Pure Core | Locations, fewer stops, route output and the cache wrapper are Django-free (AST tests); Django only in `api/` and `web/` | Pass |
| IV. Test-First, Offline Tests | Unit tests first for every new pure module; API tests with respx and fixtures, no network | Pass |
| V. Explicit Units and Decimal Money | Request numbers parsed to `Decimal`; floats converted at the optimizer boundary (R5); unit-suffixed field names; precision per the clarification (D10 updated) | Pass |
| VI. Documented Data Assumptions | README: coordinates rule (25 mi), 2-letter states, cache (24 h, per process), min-saving option, precisions, timings | Pass (README in this feature) |
| VII. Simplicity (+ cache amendment) | LocMem cache only, as amended; no new dependency; the page is one template with a CDN script | Pass |
| VIII. Zero-Setup Reviewer Run | OSRM needs no key; OSM tiles need no key; no build step | Pass |
| Technical Constraints: enums | `ErrorCode` `StrEnum` in `api/enums.py` | Pass |
| Technical Constraints: services | `api/services/route_plan.py`, `api/services/places.py`; view/serializers/presenter only parse, call, format, map errors | Pass |

**Post-design re-check:** all gates still pass. No complexity to justify.

## Project Structure

### Documentation (this feature)

```text
specs/004-route-plan-api/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/route_plan_api.md
├── checklists/requirements.md
└── tasks.md            # /speckit-tasks
```

### Source Code (repository root)

```text
planner/
├── locations.py                 # Place, PlaceIndex, load_place_index, resolve_name, resolve_point, errors
├── fewer_stops.py               # FewerStopsResult, plan_with_min_saving
└── route_output.py              # thin_line, point_at_mile, route_geojson

routing/
└── cached.py                    # CachedRoutingProvider, cache_key

api/
├── enums.py                     # ErrorCode (StrEnum)
├── services/
│   ├── __init__.py
│   ├── places.py                # get_place_index(): lru_cache, reads PLACES_INDEX_FILE
│   └── route_plan.py            # RoutePlanInput, RoutePlanResult, SameLocation, plan_route()
├── serializers.py               # LocationField, RoutePlanRequestSerializer
├── presenters.py                # result -> response dict (precision, GeoJSON); error body helper
├── exceptions.py                # DRF exception handler: same error body for parse errors
├── views.py                     # RoutePlanView (post; get optional)
└── urls.py                      # api/v1/route-plan/

web/
├── views.py                     # MapView (TemplateView)
├── urls.py
└── templates/web/map.html       # Leaflet page

config/settings.py               # REST_FRAMEWORK, CACHES, ROUTE_CACHE_TTL_SECONDS, ROUTING_RETRY_AFTER_SECONDS, PLACES_INDEX_FILE
config/urls.py                   # include api and web

tests/
├── fixtures/stations_route_plan.json        # stations on the recorded Dallas → Chicago geometry
├── unit/planner/{test_locations,test_fewer_stops,test_route_output}.py
├── unit/routing/test_cached.py
├── unit/api/{__init__,test_enums,test_serializers,test_presenters}.py
└── integration/api/{__init__,conftest,test_route_plan_api,test_errors,test_cache,test_map_page}.py
```

**Structure Decision**: pure logic joins the existing `planner/` and `routing/` packages; the
Django composition lives in the `api` app's services (constitution services rule), not in
`planner/`. The `web` app only serves the page.

## Implementation notes for `/speckit-tasks`

- **TDD order:**
  1. fixtures: `stations_route_plan.json` (4 stations placed on points of the recorded route at
     roughly miles 150, 300, 450, 700, plus one 30 mi off the route), and a small place-file
     builder helper for unit tests;
  2. `planner/locations.py` tests then code (names, compact names, 2-letter rule, territories and
     provinces, unknown codes, nearest place within/beyond 25 mi);
  3. `routing/cached.py` tests then code (miss → 1 call, hit → 0, failure not stored, key rounding,
     −0.0);
  4. `planner/fewer_stops.py` tests then code (0 → identical to `plan_refuelling`; the invariant;
     tie order; a needed stop never dropped; validation; the real-route example as a small
     hand-made case);
  5. `planner/route_output.py` tests then code (thinning bounds and last point; point at mile;
     GeoJSON shape);
  6. `api/enums.py`, serializers, presenter tests then code (precision; tolerance check);
  7. service + view + URLs; integration tests: happy path (shape, 1 call), cached repeat (0 calls,
     identical plan), each error case incl. the same-location guard cases from the spec, 422 gap
     and start-fuel details, 503 with `Retry-After`, station data missing, min-saving request;
  8. map page (200, contains the form) and the template;
  9. optional GET (drop first);
  10. manual: real request, timings, map renders, README (assumptions, API, timings, min-saving
      example), Postman collection with the min-saving request.
- **Test settings:** clear the cache and the `lru_cache`d indexes in an autouse fixture for API
  tests.

## Complexity Tracking

No constitution violations. Nothing to justify.
