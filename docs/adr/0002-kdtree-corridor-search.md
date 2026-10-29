# ADR-0002: KD-tree on 3D unit vectors for route corridor search

- Status: Accepted · Date: 2026-10-29
- Related: [route-corridor-search.md](../algorithms/route-corridor-search.md), Feature 002, F3/N2/D3/D7

## Context

Each request must find which of ~6,600 stations lie within `CORRIDOR_MILES` of a polyline up to
~3,000 miles long, and where along the route each one sits. Requirements:

- a few milliseconds;
- no external calls and no spatial database (SQLite, zero setup);
- a radius that is correct in miles at every US latitude;
- no misses on long, sparsely sampled segments.

## Decision

- Embed station coordinates as 3D unit vectors in a `scipy.spatial.cKDTree`, built lazily once.
- Per request:
  1. Resample the route by interpolation to `min(1 mi, r/2)`.
  2. Query with the chord length for `r + s/2`.
  3. Project each candidate to its nearest dense route point to get its mile marker, rescaled to the provider distance.
  4. Sort by `(mile_marker, opis_id)`.

## Rejected alternatives

| Option | Why not |
| --- | --- |
| Brute-force distance matrix | ~20M distances per request: too slow and memory-heavy |
| KD-tree on raw lat/lng | A radius in degrees is ~20% narrower (east–west) in Montana than in Texas |
| BallTree with haversine (scikit-learn) | Correct, but adds a dependency for one function |
| PostGIS `ST_DWithin` | Breaks the zero-setup run; it is the production path |
| Per-request Overpass corridor query | A second external call, slow, and no OPIS IDs |

## Consequences

- Exact in miles and fast, with deterministic output. Testable on synthetic routes.
- Mile markers carry ≤ 0.5 mi error. On looping routes a station takes its earliest nearest point.
- The index is rebuilt only on restart. That is fine for static data; live prices would need invalidation or PostGIS.
