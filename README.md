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
- [ ] 002 route-candidates: one routing call + KD-tree corridor search (planned)
- [ ] 003 refuel-optimizer: optimal greedy refuelling plan (planned)
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
 -> places index (committed)             4. resample route, cumulative miles
 -> FuelStation + FuelPrice              5. KD-tree: stations within corridor + mile markers
 -> report + fixture stations.json       6. optimizer: cheapest refuel plan (Decimal)
 -> [stretch] OSM coordinates            7. GeoJSON + totals + timings + meta

FIRST USE: stations + KD-tree loaded into memory once (lazy, lru_cache)
```

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

`loaddata stations` loads the committed `stations/fixtures/stations.json` (6,618 stations, 7,522
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

**Measured on a 2018 MacBook Pro (Intel i7-8750H, Python 3.15.2):** full rebuild 11.2 s, and
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
Rows read 8,151 | Canadian rows dropped 620 | US price rows read 7,531 | price rows stored 7,522
Stations kept 6,626 | with several prices 568
Stations located 6,618 (99.9%, threshold 95%) | city_centroid 100% | osm 0%
Stations dropped 8 (not found 6, rejected match 2) -> data/reports/unmatched_cities.csv
Places index 31,503 places, 0.6 MB
```

Cities are matched in three tiers: main name, then alternate name, then a compact key (spaces
removed and a leading N/S/E/W spelled out), so `De Forest` finds `DeForest` and `S Coffeyville`
finds `South Coffeyville`. 6 stations are not found, because
their cities are not populated places in GeoNames: townships (`Crescent, PA`, `Corinth, ME`), a
reservation (`Pueblo Of Acoma, NM`) and a marina area (`Willow Beach, AZ` ×3). A committed,
hand-reviewed list, [data/overrides/rejected_matches.csv](data/overrides/rejected_matches.csv),
rejects known-wrong matches and never supplies coordinates. A wrong location is worse than a
missing one. It drops `Willington, CT` (2 stations), which GeoNames would otherwise place at
Millington, about 28 miles away. All 8 are listed with their reason in
[data/reports/unmatched_cities.csv](data/reports/unmatched_cities.csv).

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
11. There is no safety reserve by default (`reserve_gallons = 0`).

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
| 422 | `infeasible_route` | A stretch longer than the vehicle range with no reachable station |
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
- OpenStreetMap contributors (ODbL), only if feature 005 ships.

## Future work

- PostgreSQL + PostGIS with a spatial index instead of the in-memory KD-tree
- Exact station coordinates
- Use GeoNames admin areas (towns and townships, class A/ADM3) as an extra tier before alternate names. That would place Willington CT correctly and recover Crescent PA and Corinth ME.
- Detour cost for off-route stations
- Live prices
- A truck routing profile
- A minimum saving per extra stop (a purely cost-optimal plan can add a nearby stop for a small saving)
- Mark 3.15 as officially supported once Django 6.1.3 is released.
