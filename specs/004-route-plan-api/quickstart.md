# Quickstart: Route Plan API (004)

## 1. Offline tests

```bash
python -m pytest tests/unit/planner tests/unit/routing tests/unit/api tests/integration/api \
  --cov=planner --cov=routing --cov=api --cov-report=term-missing
```

Expected: all green with no network (respx blocks real calls).

## 2. Run the server

```bash
python manage.py migrate && python manage.py loaddata stations
python manage.py runserver
```

## 3. One real request (needs the internet)

```bash
curl -s -X POST localhost:8000/api/v1/route-plan/ -H 'Content-Type: application/json' \
  -d '{"start": "Dallas, TX", "finish": "Chicago, IL"}' | python -m json.tool | head -40
```

Expected: 200; `meta.routing_calls` 1, `cached` false; about 966 miles; 4 stops, $134.59 (the
cheapest plan from the Dallas city centre). Repeat it: `routing_calls` 0, `cached` true, identical
`fuel_stops` and `summary`.

## 4. Minimum saving per stop

Same request with `"min_saving_per_stop_usd": 5`. Expected: 2 stops, $134.76,
`stops_dropped` 2, `extra_cost_vs_cheapest_usd` 0.17, `routing_calls` 0 (cached route).

## 5. Errors

| Request | Expected |
| --- | --- |
| `{"start": "Dallas, Texas", "finish": "Chicago, IL"}` | 400 `location_not_found`, message asks for a 2-letter code |
| `{"start": {"lat": 19.43, "lng": -99.13}, "finish": "Chicago, IL"}` | 400 `location_outside_us` |
| `{"start": "Dallas, TX", "finish": "dallas, tx"}` | 400 `same_location` |
| `{"start": "Dallas, TX", "finish": "Chicago, IL", "start_fuel_gallons": 60}` | 400 `invalid_input` |
| `{"start": {"lat": 32.90, "lng": -97.04}, "finish": "Chicago, IL", "start_fuel_gallons": 0}` | 422 `infeasible_route`, start fuel insufficient. (From `"Dallas, TX"` an empty tank is feasible: Dallas stations share the city-centre point, so there is a station at mile 0.) |

## 6. Map page

Open `http://localhost:8000/`, plan Dallas, TX → Chicago, IL and New York, NY → Los Angeles, CA.
Expected: the route line, numbered stop markers with name, price, gallons and cost, and the summary
panel. An unknown city shows the error message.

## 7. Timing (SC-004, by hand)

Time a first and a repeated Dallas → Chicago request (`meta.timings_ms.total` and wall clock).
Targets: cached under 100 ms; first = routing time + under 100 ms. Record the figures and the
machine in the README.
