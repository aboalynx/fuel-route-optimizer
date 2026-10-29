# Algorithm: route corridor search and mile-marker projection

Modules `planner/geometry.py`, `planner/corridor.py`, `stations/index.py` · Feature 002 · [ADR-0002](../adr/0002-kdtree-corridor-search.md)

## Context

The router returns a polyline (thousands of points) and a distance `D`. From ~6,600 in-memory
stations we need those within `r = CORRIDOR_MILES` (default 10) of the route. For each one we need
its mile marker (distance along the route) and its off-route distance. All of this must take
milliseconds, with no external calls.

## Decision

```text
startup (lazy, lru_cache'd get_station_index(); never in AppConfig.ready()):
    station_vectors = unit_vectors(lat, lng); station_tree = cKDTree(station_vectors)

per request:
    dense  = resample(polyline, s = min(1 mi, r/2))      # interpolate, don't just down-sample
    cum    = cumulative haversine miles; cum *= D / cum[-1]   # same scale as the optimizer's D
    hits   = station_tree.query_ball_point(unit_vectors(dense), chord(r + s/2))
    k, d   = cKDTree(unit_vectors(dense)).query(station_vectors[hits])
    return sorted(Candidate(opis_id, cum[k], arc_miles(d)), key=(mile_marker, opis_id))
```

- `unit_vectors(φ, λ) = (cos φ cos λ, cos φ sin λ, sin φ)`
- `chord(r) = 2·sin(r / 2R_E)`
- `arc_miles(c) = 2·R_E·asin(c/2)`, with `R_E = 3958.8` mi

Points are embedded in 3D because a radius in degrees is wrong. A degree of longitude is ~59 mi in
Texas but ~47 mi in Montana, so the corridor would be about 20% narrower in the north.

Resampling matters because interstate vertices can be 20+ miles apart, and a station near a segment's
midpoint would otherwise be missed. Querying with `r + s/2` guarantees no misses. Mile-marker and
off-route errors stay at or below `s/2` (0.5 mi).

## Rejected alternatives

- A brute-force distance matrix: 20M haversines per request is too slow.
- A KD-tree on raw lat/lng: distorted by latitude.
- A haversine BallTree: adds scikit-learn.
- PostGIS: breaks the zero-setup run; it is the production path.
- A per-request Overpass query: a second external call, and it has no OPIS IDs.

## Consequences

- Exact in miles everywhere, and fast (a few ms on a coast-to-coast route).
- Deterministic ordering.
- Mile markers carry ≤ 0.5 mi error. On a route that loops back, a station takes its earliest nearest point.
- The index is rebuilt only on process restart, which is fine for static data.
