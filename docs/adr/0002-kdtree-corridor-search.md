# ADR-0002: KD-tree on 3D unit vectors for route corridor search

- Status: Accepted · Date: 2026-10-29 · Amended 2026-10-29 (exact segment measurement, spec 002 clarification)
- Related: [route-corridor-search.md](../algorithms/route-corridor-search.md), Feature 002, F3/N2/D3/D7

## Context

Each request must find which of ~6,600 stations lie within `CORRIDOR_MILES` of a polyline up to
~3,000 miles long, and where along the route each one sits. Requirements:

- a few milliseconds;
- no external calls and no spatial database (SQLite, zero setup);
- a radius that is correct in miles at every US latitude;
- no misses on long, sparsely sampled segments;
- 0.05-mile accuracy, with a station on the route reading 0 (spec 002, FR-011).

## Decision

- Embed station coordinates as 3D unit vectors in a `scipy.spatial.cKDTree`, built lazily once.
- Per request:
  1. Densify the route: keep every original point and insert interpolated points so no segment is longer than `s = min(1 mi, r/2)`. There is no corner-cutting on curves.
  2. **Gather** candidates with one vectorized nearest-neighbour query of all stations against a KD-tree of the densified route, bounded at the chord length for `r + s/2`. No station within `r` is missed, and this is much faster than a ball query from ~10 route points per mile (measured 27 ms Dallas → Chicago, 54 ms for 3,423 miles).
  3. **Measure** each candidate exactly. Project it onto the densified segments adjacent to its nearest point, in a local equirectangular frame. That gives the exact off-route distance and the mile marker, rescaled to the provider distance.
  4. Include a station **if and only if** its exact off-route distance ≤ `r`.
  5. Sort by `(mile_marker, opis_id)`.

## Rejected alternatives

| Option | Why not |
| --- | --- |
| Brute-force distance matrix | ~20M distances per request: too slow and memory-heavy |
| KD-tree on raw lat/lng | A radius in degrees is ~20% narrower (east–west) in Montana than in Texas |
| Nearest-sample distance as the result (original version of this ADR) | Up to 0.5 mi error; a station on the route reads 0.5, not 0 |
| BallTree with haversine (scikit-learn) | Correct, but adds a dependency for one function |
| PostGIS `ST_DWithin` | Breaks the zero-setup run; it is the production path |
| Per-request Overpass corridor query | A second external call, slow, and no OPIS IDs |
| Redis for the index, or Redis GEOSEARCH | A round-trip plus deserialization per request, or many per-point calls per route; extra infrastructure. See [research R7](../../specs/002-route-candidates/research.md) |

## Consequences

- Exact in miles to well under 0.05 mi, fast and deterministic. Testable on synthetic routes, including the 9.99 / 10.01 mi boundary.
- On looping routes, the nearest pass wins, and ties go to the earliest mile marker.
- The index is rebuilt only on restart. That is fine for static data; live prices would need invalidation or PostGIS.
