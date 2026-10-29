# Contract: Route Plan API

The public HTTP surface. Value types are in [data-model.md](../data-model.md).

## `POST /api/v1/route-plan/`

```http
POST /api/v1/route-plan/
Content-Type: application/json

{"start": "Dallas, TX", "finish": "Chicago, IL"}
```

Optional fields: `start_fuel_gallons` (0..capacity, default full), `corridor_miles` (1..25, default
10), `reserve_gallons` (0..25, default 0), `min_saving_per_stop_usd` (0..100, default 0 = off).
`start` and `finish` may also be `{"lat": 32.78, "lng": -96.80}`; then `name` in the response is the nearest place (e.g. `"Dallas, TX"`). Unknown fields → 400.

### 200 response

```json
{
  "start":  {"query": "dallas, tx",  "name": "Dallas, TX",  "lat": 32.78306, "lng": -96.80667},
  "finish": {"query": "Chicago, IL", "name": "Chicago, IL", "lat": 41.85003, "lng": -87.65005},
  "summary": {
    "distance_miles": 966.452,
    "total_gallons_consumed": 96.6452,
    "gallons_purchased": 46.6452,
    "total_fuel_cost_usd": 134.81,
    "stops_count": 2,
    "stops_dropped": 2,
    "extra_cost_vs_cheapest_usd": 0.17,
    "fuel_left_gallons": 0.0,
    "assumptions": {"mpg": 10, "max_range_miles": 500, "tank_capacity_gallons": 50,
                    "start_fuel_gallons": 50, "corridor_miles": 10, "reserve_gallons": 0,
                    "min_saving_per_stop_usd": 5}
  },
  "fuel_stops": [
    {"sequence": 1, "opis_id": 68256, "name": "...", "address": "...", "city": "...", "state": "OK",
     "lat": 0.0, "lng": 0.0, "geo_source": "city_centroid", "mile_marker": 162.848,
     "off_route_miles": 1.234, "price_usd_per_gallon": 2.81733333, "gallons": 16.2848,
     "cost_usd": 45.88}
  ],
  "map": {"type": "FeatureCollection", "features": [
    {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[-96.8, 32.78], "..."]},
     "properties": {"kind": "route"}},
    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0.0, 0.0]},
     "properties": {"kind": "fuel_stop", "sequence": 1, "opis_id": 68256, "name": "...",
                    "price_usd_per_gallon": 2.81733333, "gallons": 16.2848, "cost_usd": 45.88}}
  ]},
  "meta": {"routing_provider": "osrm", "routing_calls": 1, "cached": false,
           "candidate_stations_considered": 202,
           "timings_ms": {"resolve": 1, "routing": 640, "candidates": 27, "optimize": 2, "total": 671}}
}
```

Illustrative numbers (Dallas → Chicago with `min_saving_per_stop_usd = 5`); the shape is the
contract.

**Precision:** money 2 dp (ROUND_HALF_UP), gallons 4 dp, price per gallon exact as stored (up to
8 dp), miles 3 dp. JSON numbers drop trailing zeros. `total_fuel_cost_usd` = sum of `cost_usd`;
per stop `|gallons × price_usd_per_gallon − cost_usd| ≤ 0.005`.

### Errors

Body: `{"error": {"code": "...", "message": "...", "details": {...}}}`.

| Status | `code` | When | `details` |
| --- | --- | --- | --- |
| 400 | `invalid_input` | Malformed JSON, missing/unknown fields, out-of-range values, start fuel above capacity, reserve not below capacity, start fuel below reserve | `{"fields": {"<field>": ["<message>"]}}`; vehicle-dependent checks also give `"field"` |
| 400 | `location_not_found` | Unknown city, or the state is not a 2-letter code | `{"field": "start"\|"finish", "query": "..."}` |
| 400 | `location_outside_us` | Coordinates > 25 mi from any US place, or a non-US state/territory code | `{"field", "query"}` |
| 400 | `same_location` | Same point after rounding to 4 dp, or a route shorter than 0.01 mi | `{"start", "finish"}` |
| 422 | `infeasible_route` | Station gap, or start fuel too low | `{"reason", "gap_start_mile", "gap_end_mile", "gap_start": {lat, lng}, "gap_end": {lat, lng}, "usable_range_miles"}` plus, for start fuel, `"start_fuel_gallons", "reserve_gallons", "gallons_short"` |
| 503 | `routing_unavailable` | Routing timeout, network/server error, rate limit, invalid response, no route, not near a road | `{"reason"}`; header `Retry-After` (provider's value, else 30) |
| 503 | `station_data_missing` | Station data not loaded (message says to run `loaddata stations`) | `{}` |
| 503 | `place_data_missing` | The committed place file is missing or unreadable; message "place data missing: data/places/us_places.csv.gz (restore it from git or rebuild with python manage.py build_station_data)" | `{}` |
| 500 | `internal_error` | Any other failure (a bug). Message "internal error"; the traceback is logged, never returned | `{}` |

## `GET /api/v1/route-plan/` (optional, first to drop)

Same fields as query parameters: `start`/`finish` as `"City, ST"` or `"lat,lng"`. Same response as
POST.

## `GET /` (map page)

HTML page: form, OpenStreetMap map (Leaflet), summary panel, error box. Calls the POST endpoint.
