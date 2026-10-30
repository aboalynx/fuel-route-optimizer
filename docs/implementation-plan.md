# Fuel Route Optimizer API: Requirements and Implementation Plan

| Field | Value |
| --- | --- |
| Constitution | `.specify/memory/constitution.md` (v1.1.0 after the Phase 0 amendment) |
| Workflow | Spec-Kit, one feature at a time (Section 7) |
| Features | 001 station-data-pipeline · 002 route-candidates · 003 refuel-optimizer · 004 route-plan-api · 005 osm-precision-layer (stretch) |

This document is the entry point for building the project with Spec-Kit. It covers:

- the requirements, with stable IDs;
- the decisions;
- the architecture;
- the work, split into five Spec-Kit features. Each feature has paste-ready inputs for `/speckit-specify` and `/speckit-plan`.

Section 10 maps every requirement, decision, deliverable and test to a feature.

| Algorithm | Detail document | Decision record |
| --- | --- | --- |
| Optimal refuelling (greedy "next cheaper station") | [algorithms/refuelling-greedy.md](algorithms/refuelling-greedy.md) | [ADR-0001](adr/0001-greedy-refuelling-optimizer.md) |
| Route corridor search (densifying, KD-tree, mile markers) | [algorithms/route-corridor-search.md](algorithms/route-corridor-search.md) | [ADR-0002](adr/0002-kdtree-corridor-search.md) |
| Offline station geocoding (GeoNames city centroids) | [algorithms/station-geocoding.md](algorithms/station-geocoding.md) | [ADR-0003](adr/0003-offline-centroid-geocoding.md) |
| OSM precision matching (fuzzy name matching) | [algorithms/osm-name-matching.md](algorithms/osm-name-matching.md) | [ADR-0004](adr/0004-osm-fuzzy-name-matching.md) |

---

## 1. Context and goals

The service plans fuel stops for a truck trip inside the USA. A dispatcher sends a start and a
finish. The service returns:

- the driving route, ready to draw on a map;
- the fuel stops to make and how much to buy at each;
- the total fuel cost, based on a provided list of diesel prices per station.

Goals:

- **Deterministic cost.** The same request always produces the same plan and the same total. Money is computed exactly and is reproducible.
- **Fast response.** All heavy work (cleaning prices, geocoding stations, building spatial indexes) is done offline or once at startup. A request does only cheap, in-memory computation.
- **One external call.** Each request makes at most one call to a free routing service. Location lookup, station search and optimisation are all local.
- **Optimal and explainable.** Stops are chosen by a provably optimal algorithm. The framework is a thin shell around pure, tested functions.

There is no LLM or other non-deterministic component in the request path.

## 2. Requirements

### 2.1 Functional

| ID | Requirement |
| --- | --- |
| F1 | Accept a start and a finish location, both inside the USA. |
| F2 | Return the route so it can be drawn on a map. |
| F3 | Return the fuel stops along the route, chosen to be cost-effective using the provided prices. |
| F4 | The vehicle's maximum range is 500 miles, so long routes may need several stops. |
| F5 | Return the total money spent on fuel, at 10 miles per gallon. |
| F6 | Use the provided CSV as the only price source. |
| F7 | Use a free map/routing API. |

### 2.2 Non-functional

| ID | Requirement | Target |
| --- | --- | --- |
| N1 | Latest stable Django | Django 6.1.2. Python 3.13–3.14 officially (Django 6.1.2); also developed and CI-tested on 3.15. Django adds official 3.15 support in 6.1.3. |
| N2 | Fast response | Under ~1.5 s end to end on a cold route; under 100 ms on a cached route |
| N3 | Few routing API calls | Exactly 1 per request (0 on a cache hit); start and finish resolved locally |
| N4 | Easy setup | Clone, install, migrate, load data, run: no API keys, no geocoding step |
| N5 | Demonstrable | A Postman collection and a short demo video |

### 2.3 Derived numbers

- Tank capacity = `VEHICLE_MAX_RANGE_MILES / VEHICLE_MPG` = 500 ÷ 10 = **50 gallons**. It is derived, never configured separately.
- Fuel consumed = distance ÷ 10. For example, 925 miles needs 92.5 gallons, so a truck that starts full makes at least one stop.
- CSV prices are USD per gallon (diesel retail, OPIS data).

### 2.4 Scope

- Pre-trip planning, not live tracking. One request returns one complete plan, and nothing is stored between requests.
- One required endpoint: `POST /api/v1/route-plan/`. A Leaflet map page calls the same service.
- The start may be given as coordinates. It is still the start of a new trip.
- Return only the **recommended** stops, in route order, not every station along the corridor.
- An empty stop list is valid: a trip under 500 miles that starts with a full tank needs no stop.
- `meta.candidate_stations_considered` shows how many options the optimizer compared.

### 2.5 Deliverables

| ID | Deliverable |
| --- | --- |
| DL1 | Public GitHub repo with a clean commit history in logical steps |
| DL2 | README: what it does, run in under 5 commands, API example, decisions, assumptions, trade-offs, future work, CI badge |
| DL3 | Committed fixture `stations/fixtures/stations.json` plus the management command that regenerates it |
| DL4 | One endpoint satisfying F1–F7 that returns GeoJSON for the map |
| DL5 | Leaflet HTML map page using the same service |
| DL6 | Tests: unit tests for every pure module, integration tests for the pipeline and API, no real network, CI green on GitHub Actions |
| DL7 | Postman collection at `docs/postman_collection.json` |
| DL8 | Demo video (5 minutes max), linked in the README |
| DL9 | Response includes per-step timings and the number of external calls |

## 3. Data profile of the CSV

File: `data/fuel-prices-for-be-assessment.csv`. Columns: `OPIS Truckstop ID, Truckstop Name,
Address, City, State, Rack ID, Retail Price`. There are no coordinates.

| Metric | Value | Consequence |
| --- | --- | --- |
| Total rows | 8,151 | Small enough to hold in memory |
| Canadian rows | 620 | Excluded: trips are US-only and the currency is not guaranteed |
| US rows | 7,531 | All kept as raw `FuelPrice` rows |
| Unique US OPIS IDs | 6,626 | One `FuelStation` per ID |
| Unique US (city, state) pairs | 3,808 | Geocode pairs, not rows |
| US states | 48 | |
| City values with trailing spaces | 1,256 | `strip()` every value |
| US IDs with more than one row (up to 6) | 568 | De-duplication rule (D2) |
| … exact duplicates (same price) | 81 | |
| … different prices | 487 | |
| … different name spellings | 227 | Display the first spelling |
| … differing by Rack ID | 0 | Rack ID never explains the difference |
| US price range | $2.69–$6.40/gal, mean $3.43 | Keep outliers; the optimizer avoids them naturally |
| Price precision: rows with 3 decimals | 5,389 | |
| Price precision: rows with 4–8 decimals | 2,762 (2,684 with 8, e.g. `3.00733333`) | Store prices exactly as `DecimalField(max_digits=12, decimal_places=8)`. A `(6,3)` field would silently round on save. Round only in the API response |

## 4. Decisions

### 4.1 Fixed (by the constitution or already resolved)

| # | Decision | Resolution | Source |
| --- | --- | --- | --- |
| D1 | Fuel in the tank at the start | **Start full** (50 gal), so the cost is the fuel bought en route. `start_fuel_gallons` is optional (default = tank capacity, range 0 to capacity). `total_gallons_consumed` is also returned, so the "start empty" cost can be derived | Constitution VI |
| D2 | Several prices for one station | **Minimum** price per OPIS ID. Every raw row is kept in `FuelPrice`. The first spelling is used for display | Constitution VI |
| D11 | Route cache | Django LocMem cache for routing responses, keyed by provider + start/finish rounded to 4 dp, TTL 24 h. Production: switch the cache backend to Django's built-in RedisCache (settings change only) so all workers share one route cache. The station index stays in-process. Allowed by the **constitution amendment made in Phase 0** (v1.1.0, MINOR): "A bounded in-process cache (Django's built-in LocMem cache) for routing responses is permitted. It must stay optional, must not require external infrastructure, and a cache hit must not change the computed plan." | Constitution VII (amended) |

### 4.2 Recommended defaults (confirmed via `/speckit-clarify` for 001/003; already decided in the Specify input for 002/004)

| # | Decision | Recommendation | Feature |
| --- | --- | --- | --- |
| D3 | How far off the route a station may be | `CORRIDOR_MILES` = 10, overridable per request (`corridor_miles`, 1–25), because coordinates may be city centroids | 002 |
| D4 | Routing provider | **OSRM public demo** (`OSRM_BASE_URL`): no key, car profile, GeoJSON. Behind a `RoutingProvider` interface selected by `ROUTING_PROVIDER`. Valhalla (truck costing) is a stretch goal | 002 |
| D5 | Input format | Both `"City, ST"` and `{lat, lng}`. Strings are resolved with the committed places index, so routing stays the only external call | 001, 004 |
| D6 | Map output | GeoJSON `FeatureCollection` (route LineString + stop Points) and a Leaflet page | 004 |
| D7 | Storage | SQLite by default for zero-setup review. The database is configurable with `DATABASE_URL` (django-environ), e.g. PostgreSQL; psycopg is not in `requirements.txt`. Production path: PostgreSQL + PostGIS, where a spatial index would replace the in-memory KD-tree. Two tables plus a committed fixture; stations are held in memory after first use | 001, 002 |
| D8 | HTTP method | `POST /api/v1/route-plan/` with a JSON body. `GET` with query params is **optional**, and the first thing to drop if time is short | 004 |
| D9 | Station coordinates | City-centroid baseline, then offline OSM matching (stretch) with `--skip-osm` | 001, 005 |
| D10 | Money in JSON | `Decimal` internally. JSON numbers at the boundary: USD 2 dp (ROUND_HALF_UP), gallons 4 dp, price per gallon exact as stored (up to 8 dp). Total = sum of the rounded per-stop costs. Shown gallons × shown price is within half a cent of the shown cost (exact gallons at the default 10 mpg, so only the cent rounding differs). Updated in 004's clarification: with price 3 dp and gallons 2 dp a reviewer's check could be off by a few cents | 003, 004 |

### 4.3 Remaining tensions with the constitution

| Tension | Where | Resolution |
| --- | --- | --- |
| Principle V requires `Decimal` money, but OSRM distances, numpy geometry and the `VEHICLE_*` settings are floats | 001, 002, 003 | Geometry stays in float miles. The service converts mile markers, distance and the vehicle settings to `Decimal` (via `str()`, miles quantized to 0.001) **before** the optimizer. Prices are stored exactly (`DecimalField(12, 8)`, up to 8 dp as in the CSV) and come from the DB as `Decimal`. Rounding happens only at the output (D10: USD 2 dp ROUND_HALF_UP, gallons 4 dp, price exact up to 8 dp) |
| Principle VII vs. a second routing provider | 002 | Valhalla is a stretch goal. Ship OSRM first; the interface makes adding a provider a local change |
| Principle VIII vs. `"City, ST"` input | 001, 004 | `data/geonames/US.txt` is git-ignored, so the pipeline exports a small **committed places index** for the request path |

### 4.4 Assumptions (the README lists all of these, per Principle VI)

1. Canadian stations are excluded.
2. A station with several prices uses its minimum price.
3. The truck starts with a full tank (50 gal) unless `start_fuel_gallons` is given.
4. Consumption is a flat `VEHICLE_MPG` (10 mpg). Range is `VEHICLE_MAX_RANGE_MILES` (500). Tank capacity is derived from the two.
5. A station's location may be its city centroid (`geo_source = city_centroid`) rather than its exact pump location.
6. Fuel used driving off-route to a station (the detour) is ignored. Mile markers are measured along the route.
7. Stations count as "on the route" within the corridor radius (default 10 miles).
8. Any fractional amount of fuel can be bought. There is no minimum purchase.
9. The routing profile is a car profile (OSRM demo). Truck restrictions are not modelled.
10. The "inside the USA" check for coordinates uses the nearest US populated place within 25 miles. Points just across the border (e.g. Windsor, Ontario, next to Detroit) can therefore be accepted.
11. There is no safety reserve by default (`reserve_gallons = 0`). The truck may arrive at a station or the finish with an empty tank.

## 5. Architecture

```text
ONE-TIME (management command)            PER REQUEST  POST /api/v1/route-plan/
-----------------------------            -------------------------------------
fuel CSV                                 1. validate input
 -> clean, drop Canada, group by ID      2. resolve start/finish locally (places index)
 -> GeoNames lookup -> city centroids    3. routing: cache hit, or ONE provider call
 -> places index (committed)             4. densify route, cumulative miles
 -> FuelStation + FuelPrice              5. KD-tree: stations within corridor + mile markers
 -> report + fixture stations.json       6. optimizer: cheapest refuel plan (Decimal)
 -> [stretch] OSM coordinates            7. GeoJSON + totals + timings + meta

FIRST USE: stations + KD-tree loaded into memory once (lazy, lru_cache)
```

### 5.1 Components

| Module | Responsibility | Django? |
| --- | --- | --- |
| `stations/models/` | `FuelStation` (`fuel_station.py`), `FuelPrice` (`fuel_price.py`); one module per model | Yes |
| `stations/enums.py` | `GeoSource` (`StrEnum`): fixed value sets shared by models and pipeline | No |
| `stations/pipeline/clean.py` | CSV parsing, stripping, Canada filter, `Decimal` prices, grouping | No |
| `stations/pipeline/geonames.py` | GeoNames streaming, `normalise_place_name()`, lookup, places index export | No |
| `stations/pipeline/osm.py`, `matching.py` | Overpass fetch with disk cache; name cleaning and fuzzy matching (Feature 005) | No |
| `stations/services/station_data.py` | Rebuild service: runs the pure pipeline, stores atomically, exports the fixture, place lookup and unmatched file | Yes |
| `stations/management/commands/build_station_data.py` | Thin: parses flags, calls the rebuild service, prints the report, maps errors to exit codes | Yes |
| `stations/services/index_loader.py` | Station index service: in-memory arrays (ID, coordinates, exact price, name, address, city, state, `geo_source`) + KD-tree, built lazily once; raises `StationDataMissing` when empty | Reads the model once; restart for new data |
| `routing/base.py`, `routing/osrm.py` | `RoutingProvider` protocol, OSRM provider, error mapping | Settings only |
| `planner/geometry.py`, `planner/corridor.py` | Haversine, densifying, unit vectors, corridor search | No |
| `planner/optimizer.py` | The refuelling algorithm (pure function) | No |
| `planner/locations.py` | Resolve `"City, ST"` / lat-lng against the places index | No |
| `planner/services/route_plan.py` | Route-plan service: orchestrates the request path and timings | No |
| `api/` | Thin DRF layer: serializers, view, URLs, error responses; the view calls the route-plan service | Yes |
| `web/` | Leaflet template and a thin view | Yes |

### 5.2 Data model

```python
# stations/enums.py (pure Python, no Django)
class GeoSource(StrEnum):
    CITY_CENTROID = "city_centroid"
    OSM = "osm"
    # .label and .choices() give the model field its (value, label) choices


class FuelStation(models.Model):
    opis_id = models.IntegerField(primary_key=True)  # natural key = stable PK
    name = models.CharField(max_length=120)
    address = models.CharField(max_length=200)
    city = models.CharField(max_length=80)
    state = models.CharField(max_length=2, db_index=True)
    lat = models.FloatField(null=True)
    lng = models.FloatField(null=True)
    geo_source = models.CharField(max_length=20, choices=GeoSource.choices())
    match_score = models.PositiveSmallIntegerField(null=True)
    best_price = models.DecimalField(max_digits=12, decimal_places=8)  # exact; CSV has up to 8 dp


class FuelPrice(models.Model):  # raw rows, nothing lost
    station = models.ForeignKey(FuelStation, related_name="prices", on_delete=models.CASCADE)
    rack_id = models.IntegerField()
    raw_name = models.CharField(max_length=120)
    price = models.DecimalField(max_digits=12, decimal_places=8)  # exact; never (6,3)
```

### 5.3 Settings (already in `config/settings.py`)

| Setting | Default | Used by |
| --- | --- | --- |
| `VEHICLE_MAX_RANGE_MILES` | 500 | Optimizer (range; tank = range ÷ mpg) |
| `VEHICLE_MPG` | 10 | Optimizer |
| `CORRIDOR_MILES` | 10 | Corridor search default |
| `ROUTING_PROVIDER` | `osrm` | Provider factory |
| `OSRM_BASE_URL` | `https://router.project-osrm.org` | OSRM provider |
| `ROUTING_TIMEOUT_SECONDS` | 8 | Routing client |
| `FUEL_PRICES_CSV` | `data/fuel-prices-for-be-assessment.csv` | `build_station_data --csv` |
| `GEONAMES_FILE` | `data/geonames/US.txt` | `build_station_data --geonames` |
| `DATABASE_URL` | `sqlite:///<BASE_DIR>/db.sqlite3` | `DATABASES` via `env.db()` (D7) |

There is no separate tank-capacity setting. Capacity is always `VEHICLE_MAX_RANGE_MILES / VEHICLE_MPG`, so the two can never disagree.

### 5.4 API contract

```http
POST /api/v1/route-plan/
Content-Type: application/json

{ "start": "Dallas, TX", "finish": "Chicago, IL" }
// or {"start": {"lat": 32.78, "lng": -96.80}, "finish": {"lat": 41.88, "lng": -87.63}}
// optional: "start_fuel_gallons": 50, "corridor_miles": 10, "reserve_gallons": 0 (optional extra)
```

```json
{
  "start":  {"query": "Dallas, TX",  "lat": 32.78, "lng": -96.80},
  "finish": {"query": "Chicago, IL", "lat": 41.88, "lng": -87.63},
  "summary": {
    "distance_miles": 925.432,
    "total_gallons_consumed": 92.5432,
    "gallons_purchased": 42.5432,
    "total_fuel_cost_usd": 129.30,
    "stops_count": 1,
    "stops_dropped": 0,
    "extra_cost_vs_cheapest_usd": 0.00,
    "assumptions": {"mpg": 10, "max_range_miles": 500, "tank_capacity_gallons": 50,
                    "start_fuel_gallons": 50, "corridor_miles": 10, "reserve_gallons": 0,
                    "min_saving_per_stop_usd": 0}
  },
  "fuel_stops": [
    {"sequence": 1, "opis_id": 3163, "name": "QUIKTRIP #71", "address": "...",
     "city": "Tulsa", "state": "OK", "lat": 36.15, "lng": -95.99,
     "geo_source": "city_centroid", "mile_marker": 262.4, "off_route_miles": 1.8,
     "price_usd_per_gallon": 3.03933333, "gallons": 42.5432, "cost_usd": 129.30}
  ],
  "map": {"type": "FeatureCollection", "features": ["<route LineString>", "<stop Points>"]},
  "meta": {"routing_provider": "osrm", "routing_calls": 1, "cached": false,
           "candidate_stations_considered": 187,
           "timings_ms": {"resolve": 1, "routing": 640, "candidates": 4, "optimize": 1, "total": 660}}
}
```

The numbers are illustrative; the shape is the contract. Field names carry units (Principle V).
`total_fuel_cost_usd` is the sum of the rounded per-stop costs, so the response adds up exactly.

| Status | `error.code` | When |
| --- | --- | --- |
| 400 | `invalid_input` | Malformed body, out-of-range parameters |
| 400 | `location_not_found` | `"City, ST"` not in the places index, or the state is not a 2-letter code (e.g. `"Dallas, Texas"`; the message says a 2-letter state code is expected) |
| 400 | `location_outside_us` | Coordinates or state not in the USA |
| 400 | `same_location` | Start and finish resolve to the same point |
| 422 | `infeasible_route` | A stretch longer than the vehicle range, or start fuel too low to reach any station. `details` gives the gap's start/end mile and coordinates |
| 503 | `routing_unavailable` | Provider down, timed out (`ROUTING_TIMEOUT_SECONDS`), or no route. Includes `Retry-After` |

Error body: `{"error": {"code": "...", "message": "...", "details": {...}}}`.
The codes are members of an `ErrorCode` `StrEnum` (constitution, Technical Constraints), never bare strings in code.

## 6. Current state of the repo

This table is updated in the Phase 0 commit: tick each Phase 0 item off as done.

| Item | State |
| --- | --- |
| Django project `config/`, apps `stations`, `api`, `web`, empty packages `planner`, `routing` | Done |
| `.env` / `.env.example`, django-environ, settings in Section 5.3 | Done |
| ruff and pytest config in `pyproject.toml`, smoke test | Done |
| Constitution v1.1.0 (LocMem routing-cache amendment) | Done (Phase 0) |
| GeoNames `US.txt` downloaded (git-ignored) | Done |
| `.gitignore` complete; committed `__pycache__/*.pyc` untracked | Done (Phase 0) |
| Python support | Done: Python 3.13–3.14 officially (Django 6.1.2); also developed and CI-tested on 3.15. Django adds official 3.15 support in 6.1.3. Local venv: 3.15.2 (cp315 wheels exist for numpy, scipy, rapidfuzz) |
| `requirements.txt`, `requirements-dev.txt` | Done (Phase 0), pinned from the venv; Django `>=6.1.2,<6.2` |
| `.github/workflows/ci.yml` | Done (Phase 0): matrix 3.13 / 3.14 / 3.15; first run after the first push |

## 7. How to run each feature through Spec-Kit

Feature numbering is sequential (`.specify/init-options.json`), so `/speckit-specify` creates
`specs/001-…`, `specs/002-…` and so on **in creation order**. Run `/speckit-specify` for the
features in the order of this document (001 → 005), even if 003 is built alongside 002, so the
`specs/00N-*` folders match the numbers used here.

For each feature:

1. `/speckit-specify` with the **Specify input** block. It covers behaviour and acceptance only.
2. `/speckit-clarify` **only for 001 and 003**, using their **Clarify points** (recommended answers are given). For 002 and 004 the points are already decided and are part of the Specify input. 005 has fixed steps.
3. `/speckit-plan` with the **Plan input** block. It covers technical notes and links to the algorithm doc and ADR.
4. `/speckit-tasks`. Run `/speckit-analyze` (constitution and consistency check) **only for 003**, where money correctness is concentrated.
5. `/speckit-implement`, tests first (Principle IV). The feature is done only when its tests are green in CI.
6. Commit in logical steps. Merge before starting the next feature.

### Build order and time budget

```text
Phase 0  setup completion + constitution amendment          ~1 h
   |
001 station-data-pipeline                                   ~3 h
   |
   +-------------------------------+
   |                               |
002 route-candidates  ~3 h      003 refuel-optimizer ~2 h   (pure; can run in parallel with 002)
   |                               |
   +---------------+---------------+
                   |
004 route-plan-api (API + map page)                         ~3 h
                   |
005 osm-precision-layer (stretch, only if time allows)      ~2-3 h
                   |
Release  README, Postman, coverage, demo video              ~3 h
```

Ship 001–004 and Release first. 005 is optional. If time is short, drop the optional GET endpoint (D8) first.

---

## 8. Phase 0: setup completion (not a Spec-Kit feature)

Do these in order:

- [x] **Fix `.gitignore`.** Ignore `.venv/`, `__pycache__/`, `*.pyc`, `.env`, `db.sqlite3`, `.coverage`, `htmlcov/`, `.pytest_cache/`, `.ruff_cache/`, `.DS_Store`, `.local/`, `data/geonames/`, `data/cache/`, and the Spec-Kit/Claude tooling folders (`.specify/scripts/`, `.specify/templates/`, `.specify/integrations/`, `.specify/workflows/`, `.claude/`). Keep `.specify/memory/` and `specs/` tracked. Untrack committed bytecode with `git rm -r --cached --ignore-unmatch --quiet '*/__pycache__' '*.pyc'`.
- [x] **Python version.** Python 3.13–3.14 officially (Django 6.1.2); also developed and CI-tested on 3.15. Django adds official 3.15 support in 6.1.3. The local venv runs 3.15.2. `pyproject.toml` keeps `requires-python = ">=3.13"` and ruff `target-version = "py313"`.
- [x] **Requirements files** (pinned with `==` from the venv, except Django).
  - `requirements.txt` (runtime): `Django>=6.1.2,<6.2`, `djangorestframework`, `django-environ`, `numpy`, `scipy`, `httpx`, `rapidfuzz`.
  - `requirements-dev.txt`: starts with `-r requirements.txt`, then `ruff`, `pytest`, `pytest-django`, `pytest-cov`, `respx`, `pre-commit`.
- [x] **CI.** `.github/workflows/ci.yml`: on push and pull_request; matrix Python 3.13 / 3.14 / 3.15 (`fail-fast: false`, `allow-prereleases: true`) with pip cache, `pip install -r requirements-dev.txt`, `ruff check .`, `ruff format --check .`, `pytest --cov=planner --cov=stations --cov=routing --cov-report=term-missing`.
- [x] **Constitution amendment** via `/speckit-constitution` (MINOR, v1.0.0 → v1.1.0), added under Principle VII: *"A bounded in-process cache (Django's built-in LocMem cache) for routing responses is permitted. It must stay optional, must not require external infrastructure, and a cache hit must not change the computed plan."*
- [x] **Commit** `chore: complete project setup and CI` (local). CI goes green on the first push.

---

## 9. Features

### Feature 001: station-data-pipeline

**Goal:** turn the CSV into clean, de-duplicated, geocoded US stations in the DB and a committed
fixture. Also export the committed places index used to resolve `"City, ST"` input. This is the network-free baseline.

- **Covers:** F6, N4, D2, D5 (places index), D7, D9 (baseline), DL3.
- **Depends on:** Phase 0.
- **Constitution:** I (identical re-runs), III (pure pipeline modules), IV, V (Decimal prices), VI (assumptions in README), VIII (committed artifacts).
- **Algorithm:** [station-geocoding.md](algorithms/station-geocoding.md) · [ADR-0003](adr/0003-offline-centroid-geocoding.md)
- **Spec:** [specs/001-station-data-pipeline/spec.md](../specs/001-station-data-pipeline/spec.md) (specified 2026-10-29)

**Pipeline steps** (all inside `python manage.py build_station_data`)

Flags: `--csv` (default `settings.FUEL_PRICES_CSV`), `--geonames` (default `settings.GEONAMES_FILE`),
`--skip-osm` (on by default until Feature 005 exists), `--no-export`, `--min-geocoded-pct` (default 95).
If the located share is below `--min-geocoded-pct`, the command prints the report and writes
`data/reports/unmatched_cities.csv`. It then exits non-zero **before** storing or exporting, so the DB and fixture stay
unchanged. If the GeoNames file is
missing, the command stops with a clear error naming the expected path and the download source
(`https://download.geonames.org/export/dump/US.zip`). Loading the shipped fixture never needs it.

1. **Clean** (`stations/pipeline/clean.py`, pure):
   - Read the file with the `csv` module and `strip()` every value.
   - **Validate the whole file before anything is written:**
     - If a header column is missing or renamed, fail immediately.
     - Otherwise, collect every malformed-row problem as `(line, column, value, reason)`:
       - OPIS ID or Rack ID missing or not an integer;
       - price empty, not a decimal, or ≤ 0;
       - empty City or State;
       - a State that is neither US/DC nor Canadian;
       - a row that shares an OPIS ID with an earlier row but has a different City or State (`conflicts with line <n>`).
     - If there is any problem, raise one `CsvValidationError` listing the first 50 plus the total count. The command exits non-zero and nothing is written.
     - Canadian rows are valid and are dropped silently.
   - Drop Canadian rows by province code: AB, BC, MB, NB, NL, NS, NT, NU, ON, PE, QC, SK, YT.
   - Parse prices as `Decimal` from the raw string, never via float. Keep every digit (up to 8 dp). Store them in `DecimalField(max_digits=12, decimal_places=8)`.
   - Group rows by OPIS ID. For each station: display name = first spelling seen; address, city and state from the first row; `best_price` = minimum price, computed in Python `Decimal` (never with SQL arithmetic); keep every raw row.
   - Return plain dataclasses: `StationRecord` with its list of `PriceRow`.
2. **Gazetteer** (`stations/pipeline/geonames.py`, pure):
   - Stream-parse `US.txt`. It is tab-separated with no header. Columns used: 0 geonameid, 1 name, 2 asciiname, 3 alternatenames, 4 lat, 5 lng, 6 feature class, 7 feature code, 10 admin1 (= state), 14 population.
   - Keep feature class `P` only, and exclude PPLH, PPLQ and PPLW.
   - Normalise names with one `normalise_place_name()`, applied to both GeoNames names and CSV cities.
   - Build the lookup `(normalised_name, state) → place`. Tier 3 (compact key: normalised name, leading n/s/e/w expanded, spaces removed; main names only) is used only when main and alternate names both miss. Primary keys come from `name` and `asciiname`. Alternate names are used only as a fallback lookup.
   - Tie rule when several places share a key: highest population, then lowest geonameid.
3. **Assign coordinates:**
   - Each station gets its city's centroid: `lat`, `lng`, `geo_source = GeoSource.CITY_CENTROID`, `match_score = null`. A reviewed `data/overrides/manual_coordinates.csv` (OpenStreetMap coordinates) wins over the gazetteer for listed stations (`geo_source = GeoSource.MANUAL`). It is used for Willington, CT, which GeoNames does not have.
   - Unmatched stations are excluded from the tables, together with their price rows, and written to `data/reports/unmatched_cities.csv` (`opis_id, name, city, state, reason`, ordered by `opis_id`; reason `not found` or `rejected match: <name>`). A committed, reviewed `data/overrides/rejected_matches.csv` (city, state, matched_name, reason) rejects known-wrong matches. It never supplies coordinates. That file is **committed**, so reviewers see every dropped station.
4. **Places index:**
   - Export `data/places/us_places.csv.gz` (`normalised_name, display_name, state, lat, lng, population`).
   - Include feature class `P` places with population > 0, plus every place matched by a station city.
   - Exactly one row per `(normalised_name, state)`. A main name always wins: an alternate-name or compact-tier row is added under the station's normalised city key only for a place a station matched through that tier, and only when no main name already uses the key.
   - Ordered by `(state, normalised_name)`; gzip with `mtime=0` and no stored filename, so the bytes are identical on every run.
   - Commit the file. Report its size. Measured: 31,503 places, 0.6 MB.
5. **Store:** inside `transaction.atomic()`:
   - delete all existing rows;
   - `bulk_create` stations sorted by `opis_id` (`opis_id` is the primary key);
   - assign `FuelPrice.id` explicitly as 1..N in a fixed order (by `opis_id`, then CSV row order);
   - `bulk_create` prices.

   This makes re-runs idempotent. Explicit price ids are required: after a delete, SQLite
   AUTOINCREMENT and PostgreSQL sequences hand out new ids, which would change the fixture and
   break the byte-for-byte acceptance.
6. **Report**, printed at the end. These numbers go into the README:

   ```text
   Rows read 8,151 | Canadian rows dropped 620 | US price rows 7,531
   Stations kept 6,626 | with several prices 568
   Stations located 6,5xx (9x.x%, threshold 95%) | city_centroid 100% | osm 0%
   Stations dropped nn (not found nn, rejected match nn) -> data/reports/unmatched_cities.csv
   Places index 2x,xxx places, x.x MB
   ```

7. **Fixture:** `dumpdata stations.FuelStation stations.FuelPrice` with stable ordering (by `opis_id`) to `stations/fixtures/stations.json`, then commit it. Reviewer setup is `python manage.py migrate && python manage.py loaddata stations`. It needs no network and no `US.txt`.

**Specify input:**

```text
Build an offline station-data pipeline for the fuel route optimizer. A maintainer runs one command
that reads the provided fuel price CSV and produces a clean, de-duplicated list of US truck stops
with coordinates. The result is stored in the application database and exported to a committed data file, so
anyone can load station data with no network access and no geocoding step.

Rules:
- Trim whitespace from every value. Drop rows from Canadian provinces and territories.
- One station per OPIS Truckstop ID. Every raw price row is kept. The station's price is the
  minimum across its rows; its display name is the first spelling seen.
- Prices are stored exactly as given (up to 8 decimal places); nothing is rounded before display.
- Each station gets the coordinates of its city, found in an offline gazetteer of US populated
  places with name normalisation (case, punctuation, Saint/St, Fort/Ft, Mount/Mt, Mc names).
  Historical, abandoned and destroyed places are ignored. When several places share a name in a
  state, the most populous wins. Alternate place names are used only when the main name fails.
- Stations whose city cannot be found are excluded and listed in a reviewable report file.
- The command also exports a compact, committed index of US populated places so the API can
  resolve "City, ST" input without the full gazetteer.
- The command prints a summary report and is idempotent: re-running it gives identical data and
  an identical exported file.

Acceptance (on the provided CSV):
- 6,626 stations before geocoding; 0 Canadian stations; 7,531 price rows before unmatched
  stations are dropped.
- Every station with several rows has the minimum as its price.
- A price of 3.00733333 is stored and read back exactly.
- At least 95% of stations geocoded.
- Re-running the command produces byte-for-byte identical exported data.
- Station data can be loaded with one command and no network access.
```

**Clarify points:**

- Geocoded share below 95% → improve normalisation before accepting; never add an external geocoder.
- Normalisation direction → expand abbreviations (`st → saint`, `ft → fort`, `mt → mount`, `ste → sainte`), so `"ST LOUIS"` and `"Saint Louis"` meet at `saint louis`.

**Plan input:**

```text
Django 6.1 + SQLite. Models FuelStation and FuelPrice as in docs/implementation-plan.md section 5.2
(geo_source choices from the GeoSource StrEnum in stations/enums.py; price and best_price DecimalField(max_digits=12,
decimal_places=8) so CSV prices with up to 8 dp are stored exactly). Pure modules, no Django
imports: stations/pipeline/clean.py (csv module, strip, Canadian codes AB BC MB NB NL NS NT NU ON PE
QC SK YT, Decimal prices, group by OPIS ID -> StationRecord / PriceRow dataclasses, min price, first
spelling) and stations/pipeline/geonames.py (stream US.txt, class P minus PPLH/PPLQ/PPLW,
normalise_place_name, primary lookup from name+asciiname, alternate-name fallback, tie rule
population desc then geonameid asc, places index export). Management command build_station_data
with --csv (default settings.FUEL_PRICES_CSV), --geonames (default settings.GEONAMES_FILE),
--skip-osm (default on), --no-export, --min-geocoded-pct (default 95; below it: report + unmatched
file, exit non-zero, nothing stored or exported). FuelStation.opis_id is the primary key. Store inside
transaction.atomic(): delete all, bulk_create stations sorted by opis_id, assign FuelPrice.id
explicitly as 1..N (order: opis_id, then CSV row order), bulk_create prices. Reason: SQLite
AUTOINCREMENT and PostgreSQL sequences give new ids after a delete, which would make the fixture
differ between runs and break byte-for-byte idempotence. Write data/reports/unmatched_cities.csv and
data/places/us_places.csv.gz (gzip with mtime=0 so the bytes are stable). Print the report. Dump
stations/fixtures/stations.json ordered by opis_id. Steps: "Pipeline steps" in feature 001;
algorithm docs/algorithms/station-geocoding.md; decision docs/adr/0003. README: add the data
assumptions (Canada excluded, minimum price, centroid coordinates) in the same change.
```

**Tests** (written before the code):

- **Fixtures:**
  - `tests/fixtures/sample_fuel.csv` (~20 rows): Canadian rows, an exact duplicate ID, an ID with different prices, a name-spelling variant, trailing spaces, cities needing normalisation (`St.`/`Saint`, `Mc X`, `Ft`), and one city that does not exist.
  - `tests/fixtures/sample_geonames.txt` (~10 lines in the real `US.txt` format): two places with the same name in one state (tie rule) and one PPLH place that must be ignored.
- **Unit:**
  - clean: Canada dropped, stripping, `Decimal`, grouping, min price, first spelling.
  - validation: a sample with two bad rows exits non-zero and reports both line numbers; the DB and exported files are unchanged after the failed run; a renamed header fails immediately; more than 50 problems → the first 50 plus the total count.
  - threshold: a sample below `--min-geocoded-pct` exits non-zero and leaves the DB and fixture unchanged; the same sample passes with a lower `--min-geocoded-pct`; the report prints the threshold next to the share.
  - missing gazetteer: the command exits with a clear error naming the path and download source; existing data is untouched.
  - stable keys: two consecutive runs produce identical primary keys (stations and prices) and an identical fixture file (byte comparison).
  - precision: a price of `3.00733333` survives clean → `bulk_create` → DB read → fixture → `loaddata` exactly (`== Decimal("3.00733333")`). The sample CSV includes such a row.
  - `normalise_place_name` cases.
  - lookup: tie rule, alternate-name fallback, unmatched.
- **Integration** (pytest-django): run the command on both samples with `--skip-osm`. Check both tables, the report, the unmatched file, the places index, the fixture, and that a second run is identical.

**Done when:** the fixture and places index are committed, the report numbers are in the README, and CI is green. Load and rebuild times are measured once by hand (targets: load < 1 min, rebuild < 5 min) and written in the README with the machine, e.g. "Load: 4 s. Full rebuild: 48 s (2018 Intel MacBook Pro)". They are not asserted in CI, because `US.txt` is not on the runner and runner timings vary.

---

### Feature 002: route-candidates

**Goal:** get the route geometry and distance with exactly one HTTP call behind a swappable
provider interface. Then find the stations within the corridor and give each a mile marker and
off-route distance, in milliseconds.

- **Covers:** F2, F3 (candidate side), F7, N2, N3, D3, D4, D7 (in-memory index).
- **Depends on:** 001 (station data). Phase 0.
- **Constitution:** I (stable ordering), II, III, IV (respx mocks, no live calls), V (miles), VII, VIII (key-free default).
- **Algorithm:** [route-corridor-search.md](algorithms/route-corridor-search.md) · [ADR-0002](adr/0002-kdtree-corridor-search.md)
- **Spec:** [specs/002-route-candidates/spec.md](../specs/002-route-candidates/spec.md) (specified 2026-10-29)

**Specify input:**

```text
Provide the route-side building blocks of the fuel planner.

Routing: given start and finish coordinates inside the USA, return the driving route as an ordered
list of points plus the total distance in miles, using a free routing service that needs no API
key. Exactly one external call is made per route request. The provider is selected by
configuration so it can be replaced without code changes. Failures (timeout, network error,
provider error, no route) surface as one well-defined "routing unavailable" error with a readable
reason, never as a hang. Requests time out after a configurable limit (default 8 seconds).

Corridor search: given a route and the US fuel stations, find every station within a corridor radius
of the route (default 10 miles, configurable). For each one, report its mile marker (distance along the
route from the start) and its distance from the route in miles. Results are sorted by mile marker with a stable tie-break by station
ID. Station data is loaded into memory once, not per request.

Acceptance: coordinates are sent in the provider's required order; distance is in miles; all
routing behaviour is verifiable without network access; on a synthetic straight route stations
project to the correct mile marker within 0.5 mile; stations just inside / outside the radius are
included / excluded; stations near a long straight segment with widely spaced route points are not
missed; a 3,000-mile route with ~6,600 stations is processed in well under 100 ms on a laptop.

Decided details (no clarify step needed):
- The corridor radius may be 1-25 miles.
- The route is densified so no segment exceeds 1 mile, and at most half the radius (every original point kept).
- A station near two parts of a looping route takes the earliest mile marker among the route
  points at the minimum distance.
- Only the free no-key provider ships now; a second provider is a stretch goal.
```

**Plan input:**

```text
routing/base.py: LatLng and Route dataclasses (points, distance_miles: float, provider: str),
RoutingProvider Protocol route(start, finish) -> Route, RoutingUnavailable(reason,
retry_after_seconds: int | None), RoutingFailure StrEnum (TIMED_OUT, NETWORK_ERROR, SERVER_ERROR,
RATE_LIMITED, INVALID_RESPONSE, NO_ROUTE, NOT_NEAR_ROAD) per the enum rule, get_provider() reading
settings.ROUTING_PROVIDER (unknown name -> clear error listing allowed names).
routing/osrm.py: one httpx GET (no retries) to
{OSRM_BASE_URL}/route/v1/driving/{lng},{lat};{lng},{lat}?overview=full&geometries=geojson
(lng,lat order!), httpx.Timeout(settings.ROUTING_TIMEOUT_SECONDS) so the limit applies to connect
and to each read; map timeouts / network errors / 5xx / invalid JSON / code != "Ok" / empty routes
to RoutingUnavailable; HTTP 429 -> RATE_LIMITED with retry_after_seconds from an integer
Retry-After header, capped at 60 (missing or HTTP-date -> None); waypoints[].distance > 5 miles
(8046.72 m) -> NOT_NEAR_ROAD; meters / 1609.344 = miles; GeoJSON [lng, lat] -> LatLng(lat, lng).
planner/geometry.py (pure numpy): haversine_miles, densify (keep every point, insert interpolated points), cumulative miles,
to_unit_vectors, chord_for_miles, local equirectangular segment projection.
planner/corridor.py: find_candidates(route_points, distance_miles, index, corridor_miles) ->
list[Candidate(opis_id, mile_marker, off_route_miles, price: Decimal)]; radius 1-25 (default
settings.CORRIDOR_MILES); gather with one route-tree nearest query of every station bounded at chord(r + s/2), then measure each candidate
exactly against the segments adjacent to its nearby samples (exact off-route distance and mile
marker rescaled to the provider distance); include iff off <= r; sort by (mile_marker, opis_id).
stations/services/index_loader.py: lru_cache'd get_station_index() built lazily on first use
(never in AppConfig.ready()); holds opis_id, lat, lng, best_price (Decimal), name, address, city,
state, geo_source + the cKDTree; empty index or missing tables -> StationDataMissing("station data
not loaded: run python manage.py loaddata stations"); tests reset it with cache_clear(); new
station data needs a restart. Algorithm: docs/algorithms/route-corridor-search.md; decision:
docs/adr/0002 (amended). Tests: respx with a recorded OSRM fixture
tests/fixtures/osrm_dallas_chicago.json; synthetic routes for geometry.
```

**Tests:**

- **Routing:**
  - the URL has `lng,lat` order; meters → miles; GeoJSON is parsed into `LatLng(lat, lng)`;
  - timeout, network error, HTTP 5xx, invalid JSON and `NoRoute` → `RoutingUnavailable`, each with exactly 1 call (no retries);
  - HTTP 429 → `rate limited`: `Retry-After: 2` → 2; no header → `None`; `Retry-After: 3600` → 60; always 1 call;
  - a waypoint snapped more than 5 miles → `start/finish not near a road`;
  - the factory reads `ROUTING_PROVIDER` and rejects unknown names, listing the allowed ones.
- **Corridor:**
  - mile markers on a synthetic straight line within 0.05 mile;
  - boundary: a true 9.99 miles is included and 10.01 miles excluded;
  - a station on the route reads 0 (within 0.01 mile);
  - a sparse two-point route still finds a mid-segment station;
  - the radius is honoured in miles in both Texas and Montana;
  - the last mile marker equals the provider distance;
  - a looping route lists a station once, at the nearest pass (earliest on ties);
  - ordering is stable; candidates carry the exact `Decimal` price;
  - radius outside 1–25 → error.
- **Station index:**
  - built lazily, once, and reset in tests with `cache_clear()`;
  - holds price, name, address and `geo_source`, with no database query per search;
  - empty data → `StationDataMissing` with the `loaddata` hint (never an empty list).
- **Timing:** a smoke test, not strict in CI.

**Done when:** ✅ (2026-10-29: 966.5 mi real call; 27 ms Dallas → Chicago, 54 ms for 3,423 mi) a mocked call returns a `Route`, candidates are exact on synthetic routes (0.05 mile, on-route = 0, the 9.99/10.01 boundary), one manual OSRM call (Dallas → Chicago) works, and the timing for a long route is noted for the README.

---

### Feature 003: refuel-optimizer

**Goal:** given the sorted candidates, the route distance and the start fuel, compute the
minimum-cost refuelling plan, or report exactly where the route is infeasible.

- **Covers:** F3, F4, F5, D1, D10.
- **Depends on:** nothing at code level (pure). It consumes the `Candidate` shape from 002 and can be built in parallel with it.
- **Constitution:** I (tie-break), III, IV (TDD), V (Decimal), VII.
- **Algorithm:** [refuelling-greedy.md](algorithms/refuelling-greedy.md) · [ADR-0001](adr/0001-greedy-refuelling-optimizer.md)

**Specify input:**

```text
Given a route of known length, an ordered list of fuel stations along it (mile marker and price per
gallon), a vehicle with a fixed miles-per-gallon and maximum range (10 mpg, 500 miles, so a
50-gallon tank), and the fuel in the tank at the start (default full), compute the fuel purchase
plan with the lowest total cost that gets the vehicle from start to finish without running dry.

The plan lists each stop in route order with gallons bought and cost; stops where nothing is bought
are omitted. It returns total gallons consumed, gallons purchased and total cost. Fuel can only be
bought at stations (not at the start or finish), in any fractional amount, and the tank never
exceeds capacity. Money is exact and rounded to cents only for display. Ties between equally
priced stations follow a fixed, documented rule.

If any stretch of the route (including from the start with the given start fuel) is longer than the
vehicle can cover, the plan is infeasible and the result says where the gap starts and ends.

Optional extra (lowest priority; the first optimizer extra to drop if time is short): a safety
reserve in gallons (default 0, range 0-25) that the vehicle never dips below. The start fuel must
be at least the reserve.

Acceptance: a trip under 500 miles with a full tank has no stops and zero cost; when a cheaper
station is within range the vehicle buys only enough to reach it; when the finish is within range
and no cheaper station precedes it, the vehicle buys only enough to reach the finish; fuel balance
holds (start + purchased - left = distance / mpg); on small random instances the cost equals a
brute-force optimum; with a reserve of 5 gallons, no leg between consecutive fuel points exceeds
450 miles.
```

**Clarify points:**

- Start fuel range → 0 to tank capacity. 0 is feasible only if a station sits at the start.
- Reserve (optional extra) → `reserve_gallons` 0–25, default 0. Implemented by shrinking usable capacity to `capacity − reserve` and requiring `start_fuel ≥ reserve`; otherwise the request is invalid (400). Drop it first if time is short.
- Tie rule → a strictly lower price counts as cheaper; among equal cheapest, pick the farthest, then the lowest OPIS ID.
- Total cost → the sum of the rounded per-stop costs.

**Plan input:**

```text
planner/optimizer.py, pure, stdlib decimal only. plan_refuelling(distance_miles, stations, *,
mpg, max_range_miles, start_fuel_gallons, reserve_gallons=Decimal(0)) with all values Decimal;
tank capacity is computed inside as max_range_miles / mpg (no separate setting). Optional reserve
(drop first if short on time): require start_fuel >= reserve, then run the unchanged greedy with
usable capacity = capacity - reserve and usable start fuel = start_fuel - reserve, so the range
becomes (capacity - reserve) * mpg. The service passes Decimal(str(settings.VEHICLE_MPG))
and Decimal(str(settings.VEHICLE_MAX_RANGE_MILES)) and converts float mile markers (quantize 0.001).
Origin = node with price +inf, destination = node with price 0. Greedy "next strictly cheaper node
within range, else fill up and go to the cheapest in range" per docs/algorithms/refuelling-greedy.md;
decision docs/adr/0001. Output FuelPlan(purchases, gallons_consumed, gallons_purchased,
total_cost_usd, fuel_left_gallons) or raise InfeasibleRoute(reason, gap_start_mile, gap_end_mile).
Tests first. Brute-force oracle (tests/unit/planner/oracle.py: DP over stations x integer fuel units on
small integer instances), timeboxed to about 50 seeded random cases.
```

**Tests:**

- trip < range → no stops;
- buys only enough to reach a cheaper station;
- fills up when nothing is cheaper in range;
- buys only enough to finish;
- station gap → `InfeasibleRoute` with the gap location;
- start fuel insufficient;
- fuel balance;
- equal-price tie rule;
- oracle comparison on ~50 seeded cases;
- reserve (optional): with `reserve_gallons = 5`, no leg between consecutive fuel points (start, stops, finish) exceeds 450 miles.

**Done when:** ✅ (2026-10-29: oracle agrees on all 50 seeds; 0.8 ms on 202 real candidates) all unit tests pass, the oracle agrees on every seeded case, and coverage of `planner/optimizer.py` is ≥ 95%.

---

### Feature 004: route-plan-api

**Goal:** the public endpoint and the map page. It validates input, resolves locations locally,
uses at most one routing call, runs the corridor search and the optimizer, and returns the contract in Section 5.4.
A Leaflet page renders the result.

- **Covers:** F1, F2, F3, F5, N2, N3, D5, D6, D8, D10, D11, DL4, DL5, DL9.
- **Depends on:** 001, 002, 003, and the Phase 0 constitution amendment (cache).
- **Constitution:** I, II, III (thin view), IV, V, VI, VII (amended: LocMem cache).

**Specify input:**

```text
Expose a route-planning endpoint and a simple map page.

Endpoint: a dispatcher submits a start and a finish, each either a "City, ST" string or
latitude/longitude, plus optional start fuel (gallons, 0 to tank capacity, default full), corridor
radius (miles, default 10) and, only if the optimizer's optional reserve ships, a reserve in gallons
(0-25, default 0). The response contains:
- the resolved start and finish;
- a summary: distance in miles, total gallons consumed, gallons purchased, total fuel cost in USD,
  number of stops, and the assumptions used;
- the recommended stops in route order: station identity, location, mile marker, distance off
  route, price per gallon, gallons, cost;
- a map-ready GeoJSON FeatureCollection with the route line and stop points;
- metadata: routing provider, number of external routing calls, whether the route came from cache,
  number of candidate stations considered, and per-step timings in milliseconds.

Location names are resolved locally. The only external call is to the routing service: at most one
per request, and none when the same route was requested recently. A cache hit never changes the
plan. The same request always returns the same plan.

Errors return a consistent JSON error body:
- 400 for invalid input, an unknown location, a location outside the USA, or start equal to finish;
- 422 when the route has a stretch longer than the vehicle range with no reachable station (the
  message says where);
- 503 when the routing service is unavailable or times out (with a retry hint).

Optional, lowest priority: a GET form of the endpoint with query parameters.

Map page: one web page where a user enters a start and a finish and sees the route on an
OpenStreetMap map with numbered markers for each stop (name, price, gallons, cost) and a summary
panel (distance, total cost, stops, routing calls, total time). API errors are shown as a readable
message. No API key and no frontend build step.

Acceptance: happy path returns 200 with routing_calls = 1 and the documented shape; a repeated
request reports cached = true and routing_calls = 0 with an identical plan; each error case
returns its status and code; the map page renders a long route with its stops; "Dallas, Texas"
(a full state name) returns 400 location_not_found with a message that a 2-letter state code is
expected.

Decided details (no clarify step needed):
- "City, ST" requires a 2-letter state code. A full state name is not resolved; the 400 message
  says a 2-letter code is expected.
- Coordinates count as inside the USA when the nearest known US populated place is within 25
  miles.
- Cache: the key is the provider plus coordinates rounded to 4 decimal places. A hit skips only the
  routing call, and the plan is recomputed. Entries live for 24 hours.
- The GET form is optional; drop it first if time is short.
```

**Plan input:**

```text
planner/locations.py (pure): load data/places/us_places.csv.gz once; parse "City, ST" with the same
normalise_place_name as the pipeline; coordinates -> nearest place (KD-tree on unit vectors) within
25 mi or location_outside_us. planner/services/route_plan.py: plan_route(...) times each step with
time.perf_counter, converts floats to Decimal at the optimizer boundary, derives tank capacity from
VEHICLE_MAX_RANGE_MILES / VEHICLE_MPG, builds GeoJSON (route LineString simplified to every Nth
point if > 5,000 points; numbered stop Points). Route cache via django.core.cache (LocMem) in
routing/cached.py, injected so the service stays Django-free. api/serializers.py: input accepts str
or {lat, lng} with validated ranges; output rounding per D10 (ROUND_HALF_UP) with
DecimalField(coerce_to_string=False) or REST_FRAMEWORK["COERCE_DECIMAL_TO_STRING"] = False (DRF
default is strings). api/views.py: one APIView (post; get optional) mapping InvalidLocation -> 400,
InfeasibleRoute -> 422, RoutingUnavailable -> 503 + Retry-After. URL /api/v1/route-plan/.
web/views.py TemplateView at "/", web/templates/web/map.html with Leaflet from a CDN at a pinned
version, fetch() POST to the API, L.geoJSON for the map. Integration tests with respx mocking OSRM
and a small station fixture.
```

**Tests:**

- happy path (shape, `routing_calls = 1`, 200);
- a repeat request is cached (`routing_calls = 0`, identical plan);
- `"City, ST"` and lat/lng inputs;
- `"Dallas, Texas"` → 400 `location_not_found`, with the message saying a 2-letter state code is expected;
- 400 cases: bad body, unknown city, outside the US, same start and finish, out-of-range fuel or radius;
- 503 (respx timeout);
- 422 (fixture with a gap);
- money rounding at the boundary; the total equals the sum of the stop costs;
- map page returns 200 and contains the form;
- GET equals POST (only if GET ships).

**Done when:** ✅ (2026-10-30: real OSRM end to end, 588 offline tests green on 3.13–3.15, map page checked in a browser) the endpoint works end to end against real OSRM locally (Dallas → Chicago), all mocked tests are green, and the map page renders Dallas → Chicago and New York → Los Angeles.

**As built (2026-10-30), changes from the inputs above:**

- The request service is `api/services/route_plan.py` (the `api` app's services, per the constitution), not `planner/services/`; the place lookup is `planner/locations.py` + `api/services/places.py`; the route cache is `routing/cached.py`.
- New: `min_saving_per_stop_usd` (0–100, default 5 USD; 0 = the cheapest plan) and `minimum_possible_cost_usd` in the summary, `planner/fewer_stops.py`, see the algorithm doc's "Fewer stops". The default was 0 at first and changed to 5 after the map showed the pure optimum is impractical (New York → Los Angeles: 16 stops vs 6 for 1% more).
- D10 precision: money 2 dp, gallons 4 dp, price exact as stored; `fuel_left_gallons` and `name` in the response.
- Errors: `invalid_input` also for start fuel/reserve that do not fit the tank (`details.field`), `place_data_missing` (503) and `internal_error` (500, never leaks the exception).
- Same location: 4-dp rounding before routing, plus a guard for routes shorter than 0.01 mile.
- `"New York, NY"` is an explicit alias for GeoNames' "New York City".
- Measured: Dallas → Chicago 1.29 s first request, 64 ms cached; New York → Los Angeles 0.84 s, 16 stops (6 with a $5 minimum saving).

---

### Feature 005: osm-precision-layer (stretch, only if time allows)

**Goal:** replace city-centroid coordinates with exact OpenStreetMap coordinates where a station
can be matched confidently. This runs offline, never at request time.

- **Covers:** D9 (precision); README match-rate numbers.
- **Depends on:** 001.
- **Constitution:** I (deterministic matching), II (Overpass is offline only), IV (saved samples, no live API), VIII (fixture stays committed).
- **Algorithm:** [osm-name-matching.md](algorithms/osm-name-matching.md) · [ADR-0004](adr/0004-osm-fuzzy-name-matching.md)

**Steps:**

1. **Fetch** (`stations/pipeline/osm.py`):
   - Run one Overpass query per state: area `ISO3166-2=US-XX`; `node` and `way` with `amenity=fuel`; `out center tags`.
   - POST to `https://overpass-api.de/api/interpreter` with a 200 s timeout, one query at a time, pausing between queries.
   - Cache each response to `data/cache/osm/<STATE>.json`. A re-run reads only the cache.
2. **Match** (`stations/pipeline/matching.py`):
   - Clean names: lower-case; remove store numbers like `#1243`; remove the generic words travel center(s), travel plaza, truck stop, dba; collapse spaces.
   - Score = max of `rapidfuzz.fuzz.token_set_ratio` against the OSM `name` and against the OSM `brand`.
   - Candidates = OSM stations within 15 miles of the station's city centroid (KD-tree on 3D unit vectors).
3. **Decide:**
   - Accept only a score ≥ 85 with a single clear winner. A tie keeps the city centroid.
   - One OSM element maps to at most one OPIS station. The higher score wins; on a tie the lower `opis_id` wins. The loser keeps its centroid.
4. **Apply:**
   - Accepted matches set `lat`/`lng` from OSM, `geo_source = GeoSource.OSM`, `match_score = score`.
   - The report adds osm / city_centroid / dropped percentages.
   - Regenerate and commit the fixture, and update the README numbers.

**Specify input:**

```text
Extend the offline station-data pipeline with an optional precision step. For each US state, fetch
all fuel stations from OpenStreetMap once and cache them on disk, so re-runs make no network calls. For each
priced station, consider OpenStreetMap stations near its city and match by cleaned name/brand
similarity. Accept a match only when the score is at least 85 and there is a single clear winner;
otherwise keep the city coordinates. An OpenStreetMap station is assigned to at most one priced
station, by a fixed rule. Record the coordinate source and match score per station. The report adds
precise / city-centroid / dropped percentages. The step can be skipped with a flag, and the
project works fully without it.

Acceptance: re-running uses only the disk cache; tied candidates never move a station;
below-threshold candidates are rejected; the regenerated data file is committed with updated README
numbers.
```

**Plan input:**

```text
stations/pipeline/osm.py: fetch_state(state, cache_dir) builds the Overpass QL (area
ISO3166-2=US-XX; node+way amenity=fuel; out center tags), httpx POST to
https://overpass-api.de/api/interpreter timeout 200 s, one at a time with a pause, writes
data/cache/osm/<STATE>.json, reads the cache when present. stations/pipeline/matching.py:
clean_name, score = max(token_set_ratio vs name, vs brand), candidates within 15 mi of the
centroid via cKDTree on 3D unit vectors, accept >= 85 with a unique top score, global de-conflict
(higher score wins, tie -> lower opis_id; loser keeps centroid). build_station_data without
--skip-osm applies it. Algorithm docs/algorithms/osm-name-matching.md; decision docs/adr/0004.
Tests use tests/fixtures/overpass_sample.json and respx.
```

**Tests:**

- a cache hit on the second run (respx asserts no second HTTP call);
- way elements use `center`;
- name cleaning cases;
- match accepted;
- tie keeps the centroid;
- below threshold keeps the centroid;
- de-conflict (higher score wins; tie → lower `opis_id`).

**Done when:** the fixture is regenerated, the match rate is in the README, and CI is green.

---

### Release (not a Spec-Kit feature)

- [ ] Coverage ≥ 90% on `planner/` and `stations/pipeline/`; the overall number goes in the README.
- [ ] Every edge case in Section 10.3 is covered by a test.
- [ ] `ruff check` and `ruff format --check` clean; CI green; badge in the README.
- [ ] README (DL2) covers:
  - what the service does;
  - running it in ≤ 5 commands (`pip install -r requirements.txt`, `python manage.py migrate`, `python manage.py loaddata stations`, `python manage.py runserver`, plus a curl example);
  - an API example;
  - decisions D1–D11;
  - the assumptions in Section 4.4;
  - trade-offs: centroids, corridor radius, start full, car profile, detour ignored, no reserve by default;
  - "A purely cost-optimal plan can include two stops close together for a small saving; a minimum-saving-per-stop rule is future work.";
  - measured timings (station data load and rebuild from Feature 001; API cold/cached from Feature 004), with the machine used;
  - the `--min-geocoded-pct` used for the shipped data, and the reason, if it was below the default 95;
  - data attribution: GeoNames (CC-BY 4.0) and © OpenStreetMap contributors (ODbL), required now because `data/overrides/manual_coordinates.csv` uses OSM coordinates;
  - future work: PostGIS, exact station coordinates, detour cost, live prices, truck profile; mark 3.15 as officially supported once Django 6.1.3 is released.
- [ ] Postman collection `docs/postman_collection.json` (DL7) with five requests:
  - Dallas → Chicago;
  - a short trip with no stops;
  - New York → Los Angeles;
  - a coordinates request;
  - one error case.
- [ ] Demo video (DL8), linked in the README.

---

## 10. Traceability

### 10.1 Requirements, decisions and deliverables → features

| ID | Feature(s) | ID | Feature(s) |
| --- | --- | --- | --- |
| F1 | 004 (validation, US check) | D1 | 003, 004 |
| F2 | 002, 004 | D2 | 001 |
| F3 | 002, 003, 004 | D3 | 002 |
| F4 | 003 | D4 | 002 |
| F5 | 003, 004 | D5 | 001 (places index), 004 |
| F6 | 001 | D6 | 004 |
| F7 | 002 | D7 | 001, 002 |
| N1 | Phase 0 | D8 | 004 |
| N2 | 002, 004, Release (measurements) | D9 | 001, 005 |
| N3 | 002, 004 | D10 | 003, 004 |
| N4 | 001, Phase 0, Release | D11 | Phase 0 (amendment), 004 |
| N5 | Release | DL1 | all (commit per step) |
| DL2 | Release (+ README updates in 001, 003, 004, 005) | DL3 | 001 |
| DL4 | 004 | DL5 | 004 |
| DL6 | Phase 0 (CI), every feature | DL7 | Release |
| DL8 | Release | DL9 | 004 |

### 10.2 Test matrix

| Area | Test | Proves | Feature |
| --- | --- | --- | --- |
| Pipeline | clean: Canada dropped, values stripped, Decimal, grouping | Step 1 rules | 001 |
| Pipeline | one station per OPIS ID, all rows kept, `best_price` = min, first spelling | D2 | 001 |
| Pipeline | `normalise_place_name` cases; tie rule; alternate-name fallback; PPLH ignored | Step 2 | 001 |
| Pipeline | command end to end on samples (`--skip-osm`), second run identical | Steps 1–7, idempotence | 001 |
| Pipeline | OSM fetch uses the disk cache on the second run | No repeated Overpass calls | 005 |
| Pipeline | matching: accept, tie, below threshold, de-conflict | Matching never guesses | 005 |
| Routing | OSRM: `lng,lat` order, meters → miles, GeoJSON parsed, errors mapped | One call, clean failures | 002 |
| Routing | factory reads `ROUTING_PROVIDER` | Provider swap needs no code change | 002 |
| Geometry | mile markers on a synthetic line; radius in/out; latitude; sparse segment | Corridor is correct in miles | 002 |
| Optimizer | trip < range | No stops, cost 0 under D1 | 003 |
| Optimizer | cheaper station ahead | Buys only enough to reach it | 003 |
| Optimizer | nothing cheaper in range | Fills up, goes to the cheapest reachable | 003 |
| Optimizer | destination in range, nothing cheaper before it | Buys only enough to finish | 003 |
| Optimizer | gap > range; start fuel too low | `InfeasibleRoute` with location (→ 422) | 003 |
| Optimizer | fuel balance; equal-price tie rule | Invariants, determinism | 003 |
| Optimizer | brute-force oracle, ~50 seeded cases | Optimality (catches overbuying) | 003 |
| Optimizer | reserve 5 gal → no leg > 450 mi (optional extra) | Reserve honoured | 003 |
| Pipeline | `3.00733333` round-trips exactly through DB and fixture | No silent price rounding | 001 |
| Pipeline | two consecutive runs → identical PKs and fixture bytes | Explicit price ids, idempotence | 001 |
| API | `"Dallas, Texas"` → 400 `location_not_found` (2-letter code expected) | Clear input error | 004 |
| API | happy path (routing mocked) | Shape, `routing_calls = 1`, 200 | 004 |
| API | repeat request | `cached = true`, `routing_calls = 0`, same plan | 004 |
| API | bad input / unknown city / outside US / same location / provider down / infeasible | 400 ×4, 503, 422 with codes | 004 |
| Web | map page renders | DL5 | 004 |

### 10.3 Edge cases

| Edge case | Handling | Feature |
| --- | --- | --- |
| Trip shorter than the range | Zero stops; route and totals still returned | 003 |
| Gap > range (sparse West; a route via Ontario, e.g. Detroit → Buffalo) | 422 with gap start/end miles and coordinates | 003, 004 |
| Start or finish outside the USA, unknown city | 400 with a helpful message | 004 |
| Point just across the border (e.g. Windsor, ON) | Accepted by the 25-mile check (assumption 10) | 004 |
| Start equals finish | 400 `same_location` | 004 |
| Routing provider down or slow | 503 with `Retry-After`; timeout from `ROUTING_TIMEOUT_SECONDS` | 002, 004 |
| `start_fuel_gallons = 0` | Feasible only if a station is at mile ≈ 0; otherwise 422 | 003 |
| `reserve_gallons > start_fuel_gallons` (optional extra) | 400 `invalid_input` | 003, 004 |
