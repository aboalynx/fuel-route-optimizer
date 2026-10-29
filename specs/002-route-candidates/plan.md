# Implementation Plan: Route Candidates

**Branch**: `002-route-candidates` | **Date**: 2026-10-29 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/002-route-candidates/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

This feature builds the route side of the planner:

- **Routing:** one OSRM call per route, behind a swappable provider interface. Every failure (timeout, network, server error, rate limit, invalid response, no route, start/finish not near a road) becomes one `RoutingUnavailable` error, with no retries.
- **Corridor search:** pure numpy/scipy code that densifies the route (every original point kept, interpolated points inserted so no segment exceeds the spacing), gathers candidates with a KD-tree on 3D unit vectors, then measures each one exactly against the densified segments next to its nearest point. The result is 0.05-mile accuracy, on-route = 0, and a sharp radius boundary.
- **Station index:** the shipped station data, loaded once into memory, so a search never queries the database.

One real call measured 966.5 miles and 9,149 points in 0.5 s (research R1).

## Technical Context

**Language/Version**: Python 3.15 (venv 3.15.2). Supported: 3.13–3.14 officially (Django 6.1.2), also developed and CI-tested on 3.15.

**Primary Dependencies**: httpx (routing), numpy + scipy `cKDTree` (corridor), Django 6.1.2 (station-index service and settings only). All are already pinned in `requirements.txt`; no new dependency.

**Storage**: none new. Reads `FuelStation` (Feature 001) once per process.

**Testing**: pytest, respx (mocked httpx, no network), pytest-django for the index service.

**Target Platform**: developer laptop and the CI matrix (3.13, 3.14, 3.15).

**Project Type**: web service (Django). This feature adds pure library modules plus one Django service.

**Performance Goals**:

- `find_candidates` on a 3,000-mile route with ~6,600 stations: well under 100 ms (measured by hand, SC-004);
- index build: milliseconds, once per process.

**Constraints**:

- exactly 1 external call per route, no retries;
- a configurable timeout on connect and on each read;
- no database query per search;
- deterministic output;
- 0.05-mile accuracy, including on curves (densify, never replace, the polyline);
- a warning (not an error) is logged when provider distance ÷ geometry length is outside 0.95–1.05 on real data.

**Scale/Scope**: the densified route keeps every original point plus a few inserted ones (about 9,500 for Dallas → Chicago: 9,149 original points over 966.5 mi); a few hundred candidates per route; 6,620 stations.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle / rule | Check | Status |
| --- | --- | --- |
| I. Deterministic Results | Sorted by `(mile_marker, opis_id)`; loop ties go to the earliest mile; no randomness | Pass |
| II. Single External Routing Call | One `GET` per route; no retries, even on 429 or 5xx (R2) | Pass |
| III. Pure Core | `routing/base.py`, `routing/osrm.py`, `planner/*` take plain arguments; only `routing/factory.py` and `stations/services/index_loader.py` touch Django (R5) | Pass |
| IV. Test-First, Offline Tests | respx-mocked routing, synthetic geometry, no network in tests; tests are written first | Pass |
| V. Explicit Units and Decimal Money | `distance_miles`, `mile_marker`, `off_route_miles`; candidate `price` is the exact `Decimal` | Pass |
| VI. Documented Data Assumptions | README: restart for new data (done), the real-call result and the timing (this feature) | Pass |
| VII. Simplicity (+ v1.1.0 cache rule) | No new dependency, no cache here (the route cache is Feature 004) | Pass |
| VIII. Zero-Setup Reviewer Run | OSRM needs no key; tests need no network | Pass |
| Technical Constraints: enums | `RoutingFailure` `StrEnum`; `GeoSource` reused in `StationInfo` | Pass |
| Technical Constraints: services | The station loading lives in `stations/services/index_loader.py`; algorithms stay pure | Pass |

**Post-design re-check:** all gates still pass. No complexity to justify.

## Project Structure

### Documentation (this feature)

```text
specs/002-route-candidates/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/route_candidates.md
├── checklists/requirements.md
└── tasks.md            # /speckit-tasks
```

### Source Code (repository root)

```text
routing/                         # pure except factory.py
├── __init__.py
├── base.py                      # LatLng, Route, RoutingFailure (StrEnum), RoutingUnavailable, RoutingProvider
├── osrm.py                      # OSRMProvider: one httpx GET, failure mapping, 429 Retry-After cap
└── factory.py                   # provider_from_settings(): reads ROUTING_PROVIDER, OSRM_BASE_URL, ROUTING_TIMEOUT_SECONDS

planner/                         # pure (numpy/scipy), no Django
├── __init__.py
├── geometry.py                  # haversine, densify, cumulative miles, unit vectors, chord, local projection
├── station_index.py             # StationInfo, StationIndex, build_station_index, StationDataMissing
└── corridor.py                  # Candidate, find_candidates (gather -> exact measure -> include iff <= r)

stations/services/
└── index_loader.py              # get_station_index(): lru_cache, reads FuelStation once, maps missing data

tests/
├── fixtures/osrm_dallas_chicago.json      # trimmed recording of the real response (R1)
├── unit/routing/{__init__,test_osrm,test_factory}.py
├── unit/planner/{__init__,test_geometry,test_station_index,test_corridor}.py
└── integration/test_index_loader.py       # Django service: build once, empty DB, cache_clear
```

**Structure Decision**: `routing/` and `planner/` are plain packages, not Django apps. They hold
the pure logic. The one Django-dependent loader is a service in the `stations` app, which owns
the model. Feature 004's request service will combine routing, the index and the corridor search.

## Implementation notes for `/speckit-tasks`

- **TDD order:**
  1. the fixture;
  2. `routing/base` tests, then code;
  3. `osrm` tests (one per failure row, each asserting 1 call), then code;
  4. factory;
  5. `geometry` tests (densify keeps every original point and leaves no segment longer than the spacing), then code;
  6. `station_index` (pure) tests, then code;
  7. `corridor` tests (boundary 9.99/10.01, on-route 0, sparse segment, a curved synthetic route (an arc) with a station on the arc reading off-route ≈ 0 within 0.01 mi and the right mile marker within 0.05 mi, latitudes, loop, ordering, rescale warning outside 0.95–1.05), then code;
  8. the index-loader service (`stations/services/index_loader.py`) with integration tests;
  9. the manual real call and timing, then the README.
- **Recorded fixture:** trim the real response to about 50 geometry points, keeping the real `distance` and `waypoints`, so tests stay small and readable. Its geometry is therefore much shorter than its distance: no test may assert geometry length ≈ distance on it, and the rescale warning is expected to fire on it.
- **README:** in this feature, record the real-call result (966.5 mi) and the measured `find_candidates` timing with the machine.

## Complexity Tracking

No constitution violations. Nothing to justify.
