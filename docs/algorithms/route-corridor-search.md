# Algorithm: route corridor search and mile-marker projection

Modules `planner/geometry.py`, `planner/corridor.py`, `stations/services/index_loader.py` · Feature 002 · [ADR-0002](../adr/0002-kdtree-corridor-search.md) · [spec](../../specs/002-route-candidates/spec.md)

## Context

The router returns a polyline (thousands of points) and a distance `D`. From ~6,600 in-memory
stations we need those within `r = CORRIDOR_MILES` (default 10, allowed 1–25) of the route. For each
one we need:

- its mile marker (distance along the route);
- its off-route distance;
- its price.

Requirements:

- accuracy of 0.05 mile, and a station on the route must read 0 (spec FR-011, clarified 2026-10-29);
- milliseconds per request, no external calls, no database query.

## Decision: gather on samples, then measure exactly

```text
first use (lazy, lru_cache'd get_station_index() in stations/services/index_loader.py; never in AppConfig.ready()):
    index = arrays of opis_id, lat, lng, best_price (Decimal), name, address, city, state, geo_source
    station_vectors = unit_vectors(lat, lng)
    empty index (or missing tables) -> raise StationDataMissing

per request:
    s      = min(1 mi, r/2)
    dense  = densify(polyline, s)                        # keep every point, insert so no segment > s
    cum    = cumulative haversine miles of dense;  k = D / cum[-1]
    route_tree = cKDTree(unit_vectors(dense))
    # 1. gather: one vectorized query of every station against the route tree, bounded at r + s/2,
    #    so no station within r can be missed (it also returns each station's nearest point)
    d, nearest = route_tree.query(station_vectors, distance_upper_bound=chord(r + s/2))
    # 2. measure each candidate (d finite) exactly against the route itself
    for station in candidates:
        i0     = its nearest dense point(s) (all of them on exact ties)
        for each segment touching i0 ((i0-1, i0) and (i0, i0+1)):
            project the station onto the segment in a local equirectangular frame
            off  = distance from the station to the projected point
            mile = (cum[i] + t * len_i) * k             # t in [0, 1] along the segment
        keep the (off, mile) with the smallest off; ties -> smallest mile
    # 3. include if and only if off <= r
    return sorted(Candidate(opis_id, mile, off, price), key=(mile_marker, opis_id))
```

**Local equirectangular frame** around the station (lat₀, lng₀), with `M = π·R_E/180` ≈ 69.09 mi per
degree:

- `x = (lng − lng₀)·cos(lat₀)·M`
- `y = (lat − lat₀)·M`

The station is the origin. Its projection onto segment A→B is
`t = clamp(−A·(B−A)/|B−A|², 0, 1)`, and `off = |A + t(B−A)|`. Over 1-mile segments within about
11 miles of the station, the error from this flat approximation is far below 0.01 mile.

**Other formulas** (`R_E = 3958.8` mi):

- `unit_vectors(φ, λ) = (cos φ cos λ, cos φ sin λ, sin φ)`
- `chord(r) = 2·sin(r / 2R_E)` (straight-line distance between unit vectors `r` miles apart)

**Why each step:**

- **3D unit vectors for the gather.** A radius in degrees is wrong: a degree of longitude is ~59 mi
  in Texas and ~47 mi in Montana.
- **Querying from the stations, not from the route.** A route has about 10 points per mile, so a
  3,000-mile route has ~30,000 points; a ball query from each of them took 66 ms. One vectorized
  nearest-neighbour query of the ~6,600 stations against a tree of the route gives the same set of
  candidates (a station is within `r + s/2` of some route point iff its nearest route point is),
  plus the nearest point that step 2 needs. Measured: 27 ms on the real Dallas → Chicago route,
  54 ms on a synthetic 3,423-mile route (2018 MacBook Pro).
- **Densifying, not resampling.** Interstate vertices can be 20+ miles apart, so points are inserted. Every original point is kept, so the densified segments are sub-segments of the real polyline. Replacing the polyline with evenly spaced samples would cut corners: on a 1-mile-radius curve, a 1-mile chord is about 0.125 mi from the road.
- **Rescale check.** Mile markers are rescaled to the provider distance. If provider distance ÷ geometry length is outside 0.95–1.05, a warning is logged.
- **Gathering with `r + s/2`.** No station within `r` is missed.
- **The exact step.** It removes the sampling error. A station on the route reads 0 instead of up to
  `s/2`, and mile markers are exact along the polyline.
- **Inclusion on the exact distance.** It makes the boundary sharp: a true 9.99 mi is in and
  10.01 mi is out.

## Rejected alternatives

- Brute-force distance matrix (20M haversines per request): too slow.
- KD-tree on raw lat/lng: distorted by latitude.
- Nearest-sample distance as the answer (the original design): up to 0.5 mi error, and on-route
  stations read 0.5 instead of 0.
- Haversine BallTree: adds scikit-learn.
- PostGIS: breaks the zero-setup run; it is the production path.
- Per-request Overpass query: a second external call, and no OPIS IDs.

## Consequences

- Exact to well under 0.05 mi, in miles at every latitude, deterministic, and fast. The refine step
  touches only a few segments per candidate (a few hundred candidates per route).
- On a route that loops back, the nearest pass wins (the nearest densified point), and ties go to the earliest mile marker.
- The index is built once on first use and holds everything later features need (price, name, address,
  `geo_source`), so the request path never queries the database.
- New station data needs a process restart (spec FR-013). Tests reset the index with `cache_clear()`.
- The index is in process memory, not Redis: see [research R7](../../specs/002-route-candidates/research.md).
