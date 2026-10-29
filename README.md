# Fuel Route Optimizer API

Built as a take-home assessment for the Backend Django Engineer role at Spotter.

[![CI](https://github.com/aboalynx/fuel-route-optimizer/actions/workflows/ci.yml/badge.svg)](https://github.com/aboalynx/fuel-route-optimizer/actions/workflows/ci.yml)

The service plans fuel stops for a truck trip inside the USA. Send it a start and a finish. Using the
provided diesel prices, it returns:

- the driving route, ready to draw on a map;
- the recommended fuel stops in route order;
- the gallons to buy at each stop;
- the total fuel cost.

The vehicle has a 500-mile range and does 10 miles per gallon.

## Status

- [x] Project setup and CI (done)
- [x] 001 station-data-pipeline: clean CSV, geocode stations offline, committed fixture (done)
- [x] 002 route-candidates: one routing call + KD-tree corridor search (done)
- [x] 003 refuel-optimizer: optimal greedy refuelling plan (done)
- [ ] 004 route-plan-api: `POST /api/v1/route-plan/` + Leaflet map page (planned)
- [ ] 005 osm-precision-layer: exact station coordinates from OpenStreetMap (planned, stretch)

## How it works

**One external call per request.** Everything except routing is precomputed or done in memory.
The work splits into two flows:

- **Offline data pipeline** (one management command): clean the price CSV, de-duplicate stations,
  give each one coordinates from an offline gazetteer, and commit the result as a fixture.
- **Lean request path:** resolve the start and finish locally, make one routing call (or hit the
  cache), find the stations near the route with a KD-tree, run the optimizer, and return GeoJSON
  plus totals.

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

**Why in memory?** The station index is small (6,620 stations, about 1–2 MB) and read-only, and it
needs an in-memory spatial index (a KD-tree) to find the stations along a route quickly. Each server
process therefore holds its own copy, built once on first use, and a search never queries the
database. Redis was considered and rejected for this: every request would pay a network round-trip
plus deserialization, and it adds infrastructure a reviewer would have to run.

**Routing and corridor search.** Each route is one call to the routing service, and a failed call
is never retried, because a retry would be a second external call. Every failure (timeout, network
error, server error, rate limit, invalid response, no route, start/finish not near a road) becomes
one "routing unavailable" error with a reason. The full list is in
[specs/002-route-candidates/contracts/route_candidates.md](specs/002-route-candidates/contracts/route_candidates.md).
Stations near the route are measured exactly against the road geometry: to within 0.05 mile, and a
station on the road reads 0.

**Cheapest refuelling plan.** At each fuel point the truck buys just enough to reach the next
strictly cheaper station in range; if none is in range, it fills the tank and goes to the cheapest
one in range. The finish counts as a free station, so the truck never buys fuel it does not need to
finish. This greedy is provably optimal for the model, and the tests check it against a
brute-force optimum on 50 seeded random trips. Details:
[docs/algorithms/refuelling-greedy.md](docs/algorithms/refuelling-greedy.md). An impossible trip
returns the reason and the exact gap (for example "station gap: no fuel point between mile 100 and
mile 700"), never a partial plan.

**Measured on a 2018 MacBook Pro (Intel i7-8750H, Python 3.15.2):**

- Dallas, TX → Chicago, IL routing call: 966.5 miles, 9,149 route points, 0.5–0.8 s.
- Corridor search (10-mile radius) on that route: 202 candidate stations in 27 ms.
- Corridor search on a synthetic 3,423-mile route (34,725 points): 327 candidates in 54 ms.
- Station index: built once per process on first use, in about 0.1 s.
- Refuelling plan on the 202 Dallas → Chicago candidates: 4 stops, $134.64, in 0.8 ms.
- Refuelling plan on a synthetic 3,000-mile route with 400 stations: 1.2 ms.

## Tech stack

- Django 6.1.2, Django REST Framework
- Python 3.13–3.14 officially (Django 6.1.2); also developed and CI-tested on 3.15. Django adds official 3.15 support in 6.1.3.
- numpy and scipy (`cKDTree` for the spatial search), httpx, rapidfuzz
- Routing: OSRM public demo server (no API key)
- Database: SQLite by default, configurable via `DATABASE_URL`

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
python manage.py migrate
python manage.py loaddata stations
python -m pytest
```

`loaddata stations` loads the committed `stations/fixtures/stations.json` (6,620 stations, 7,524
price rows). It needs no network access and no gazetteer download. Running the API is planned
(feature 004).

### Rebuild station data (optional)

The shipped data is produced by one command, so you can check how it was made:

```bash
curl -LO https://download.geonames.org/export/dump/US.zip
unzip US.zip US.txt -d data/geonames/
python manage.py build_station_data
```

The command first checks the whole price file and stops, writing nothing, if any row is
malformed. It then locates each station and stores everything in one transaction. Last, it
rewrites three committed files, which come out byte-for-byte identical on every run:
`stations/fixtures/stations.json`, `data/places/us_places.csv.gz` (the place lookup used later for
`"City, ST"` input) and `data/reports/unmatched_cities.csv`. If fewer stations are located than
`--min-geocoded-pct` (default 95), it prints the report, writes the unmatched file and changes
nothing else. The shipped data was built with the default threshold of 95%.

After `build_station_data` or `loaddata`, restart the server to pick up the new station data.
(`runserver` does not reload on data changes, only on code changes.)

**Measured on a 2018 MacBook Pro (Intel i7-8750H, Python 3.15.2):** full rebuild 11.0 s, and
`loaddata stations` into a fresh database 10.1 s.

## Configuration

Set these in `.env`. Every setting has a default.

| Setting | Default | Purpose |
| --- | --- | --- |
| `VEHICLE_MAX_RANGE_MILES` | 500 | Vehicle range; tank capacity = range ÷ mpg |
| `VEHICLE_MPG` | 10 | Fuel consumption |
| `CORRIDOR_MILES` | 10 | Max distance from the route for a station to count |
| `ROUTING_PROVIDER` | `osrm` | Routing provider |
| `OSRM_BASE_URL` | `https://router.project-osrm.org` | OSRM server |
| `ROUTING_TIMEOUT_SECONDS` | 8 | Routing request timeout |
| `FUEL_PRICES_CSV` | `data/fuel-prices-for-be-assessment.csv` | Input price file |
| `GEONAMES_FILE` | `data/geonames/US.txt` | Gazetteer (needed only to rebuild station data) |
| `DATABASE_URL` | `sqlite:///<project>/db.sqlite3` | Database (e.g. PostgreSQL; psycopg is not included) |

Tank capacity is derived from range and mpg, never configured separately.

## Data and assumptions

**The price file** (`data/fuel-prices-for-be-assessment.csv`):

- 8,151 rows.
- 620 Canadian rows, which are excluded.
- 6,626 unique US stations by OPIS ID.
- When a station has several prices, the **minimum** is used. All raw rows are kept.
- Prices are stored exactly as given, up to 8 decimals, and rounded only in API output.

**Rebuild report for the shipped data:**

```text
Rows read 8,151 | Canadian rows dropped 620 | US price rows read 7,531 | price rows stored 7,524
Stations kept 6,626 | with several prices 568
Stations located 6,620 (99.9%, threshold 95%) | city_centroid 6,618 (99.97%) | manual 2 (0.03%) | osm 0 (0%)
Stations dropped 6 (not found 6, rejected match 0) -> data/reports/unmatched_cities.csv
Places index 31,503 places, 0.6 MB
```

Cities are matched in three tiers: main name, then alternate name, then a compact key (spaces
removed and a leading N/S/E/W spelled out), so `De Forest` finds `DeForest` and `S Coffeyville`
finds `South Coffeyville`. 6 stations are not found, because
their cities are not populated places in GeoNames: townships (`Crescent, PA`, `Corinth, ME`), a
reservation (`Pueblo Of Acoma, NM`) and a marina area (`Willow Beach, AZ` ×3). They are listed
with their reason in [data/reports/unmatched_cities.csv](data/reports/unmatched_cities.csv).

Two reviewed lists in `data/overrides/` handle cases the gazetteer gets wrong.
[manual_coordinates.csv](data/overrides/manual_coordinates.csv) places 2 stations at I-84 Exit 71
in Willington, CT, using coordinates from OpenStreetMap (`geo_source = manual`). GeoNames has no
Willington and would otherwise match Millington, about 28 miles away.
[rejected_matches.csv](data/overrides/rejected_matches.csv) (empty for now) can drop any future
wrong match, because a wrong location is worse than a missing one.

**Assumptions:**

1. Canadian stations are excluded.
2. A station with several prices uses its minimum price.
3. The truck starts with a full tank (50 gal) unless `start_fuel_gallons` is given.
4. Consumption is a flat `VEHICLE_MPG` (10 mpg). Range is `VEHICLE_MAX_RANGE_MILES` (500). Tank capacity is derived from the two.
5. A station's location is its city centroid (`geo_source = city_centroid`), not its exact pump location. Stations whose city is not in the gazetteer are dropped and listed in the unmatched file.
6. Fuel used driving off-route to a station (the detour) is ignored. Mile markers are measured along the route.
7. Stations count as "on the route" within the corridor radius (default 10 miles).
8. Any fractional amount of fuel can be bought. There is no minimum purchase.
9. The routing profile is a car profile (OSRM demo). Truck restrictions are not modelled.
10. The "inside the USA" check for coordinates uses the nearest US populated place within 25 miles. Points just across the border (e.g. Windsor, Ontario, next to Detroit) can therefore be accepted.
11. There is no safety reserve by default (`reserve_gallons = 0`), so the range is the brief's 500 miles. A reserve of 0–25 gallons can be requested; the tank then never drops below it (with 5 gallons, no leg is longer than 450 miles). In production a default of about 5 gallons would be sensible.
12. Money is exact: prices are never rounded before multiplying. Each stop's cost is rounded half up to cents, and the total cost is the sum of the rounded stop costs, so the stops always add up to the total shown.
13. A purely cost-optimal plan can include two stops close together for a small saving (see future work).

## API (planned, feature 004)

```http
POST /api/v1/route-plan/
Content-Type: application/json

{ "start": "Dallas, TX", "finish": "Chicago, IL" }
// or {"start": {"lat": 32.78, "lng": -96.80}, "finish": {"lat": 41.88, "lng": -87.63}}
// optional: "start_fuel_gallons": 50, "corridor_miles": 10
```

Response shape. The numbers are illustrative, not measured:

```json
{
  "start":  {"query": "Dallas, TX",  "lat": 32.78, "lng": -96.80},
  "finish": {"query": "Chicago, IL", "lat": 41.88, "lng": -87.63},
  "summary": {
    "distance_miles": 925.4, "total_gallons_consumed": 92.54, "gallons_purchased": 42.54,
    "total_fuel_cost_usd": 129.28, "stops_count": 1,
    "assumptions": {"mpg": 10, "max_range_miles": 500, "tank_capacity_gallons": 50,
                    "start_fuel_gallons": 50, "corridor_miles": 10}
  },
  "fuel_stops": [
    {"sequence": 1, "opis_id": 3163, "name": "QUIKTRIP #71", "city": "Tulsa", "state": "OK",
     "lat": 36.15, "lng": -95.99, "geo_source": "city_centroid", "mile_marker": 262.4,
     "off_route_miles": 1.8, "price_usd_per_gallon": 3.039, "gallons": 42.54, "cost_usd": 129.28}
  ],
  "map": {"type": "FeatureCollection", "features": ["<route LineString>", "<stop Points>"]},
  "meta": {"routing_provider": "osrm", "routing_calls": 1, "cached": false,
           "candidate_stations_considered": 187,
           "timings_ms": {"resolve": 1, "routing": 640, "candidates": 4, "optimize": 1, "total": 660}}
}
```

| Status | `error.code` | When |
| --- | --- | --- |
| 400 | `invalid_input` | Malformed body, out-of-range parameters |
| 400 | `location_not_found` | Unknown `"City, ST"`, or the state is not a 2-letter code |
| 400 | `location_outside_us` | Coordinates or state not in the USA |
| 400 | `same_location` | Start and finish resolve to the same point |
| 422 | `infeasible_route` | A stretch longer than the vehicle range with no reachable station, or the start fuel cannot reach the first fuel point (the body gives the reason, the gap miles and the gallons short) |
| 503 | `routing_unavailable` | Routing provider down or timed out |

Response timings for cold and cached routes are TBD after feature 004.

## Testing and quality

- **Tests:** pytest with pytest-django. Unit tests cover every pure module; integration tests cover the pipeline and the API.
- **No real network in tests.** Routing and Overpass are mocked with respx or saved samples.
- **Coverage target:** 90%+ on `planner/` and `stations/pipeline/`, and 95%+ on the optimizer.
- **Linting and formatting:** `ruff check .` and `ruff format --check .`.
- **CI:** GitHub Actions runs ruff and pytest with coverage on every push (badge above).

## Design docs

- [docs/implementation-plan.md](docs/implementation-plan.md): requirements, decisions, architecture, features
- [docs/algorithms/](docs/algorithms/): how each algorithm works
- [docs/adr/](docs/adr/): why each algorithm was chosen
- `specs/`: Spec-Kit specifications per feature (added as features are specified)

Planned with Spec-Kit before implementation; AI-assisted. Every file was reviewed, and I can explain
any part of it.

## Data attribution

- City coordinates and the committed place lookup (`data/places/us_places.csv.gz`) come from [GeoNames](https://www.geonames.org/), licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The place lookup redistributes GeoNames data.
- Station coordinates in `data/overrides/manual_coordinates.csv` come from OpenStreetMap: © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright), available under the [Open Database License (ODbL)](https://opendatacommons.org/licenses/odbl/).

## Future work

- PostgreSQL + PostGIS with a spatial index instead of the in-memory KD-tree
- Exact station coordinates
- Use GeoNames admin areas (towns and townships, class A/ADM3) as an extra tier before alternate names. That would locate Willington CT without a manual override and recover Crescent PA and Corinth ME.
- Detour cost for off-route stations
- Live prices
- A truck routing profile
- A minimum saving per extra stop (a purely cost-optimal plan can add a nearby stop for a small saving)
- Mark 3.15 as officially supported once Django 6.1.3 is released.
- Shared Redis route cache for multi-worker deployments (Django's built-in RedisCache backend, a settings change only). With LocMem each worker has its own cache.
- A station-data version marker, checked at most once every N seconds, if station data ever needs to change while the server runs (today a restart is required).
