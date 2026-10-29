# ADR-0004: Offline OSM matching with fuzzy names and a unique-winner rule

- Status: Accepted (stretch; ships only if time allows) · Date: 2026-10-29
- Related: [osm-name-matching.md](../algorithms/osm-name-matching.md), Feature 005, D9

## Context

City centroids can be miles from the real station. OSM has exact fuel-station points, but no OPIS
IDs, so linking needs name + proximity matching on noisy names (`PILOT TRAVEL CENTER #1243` vs
`brand=Pilot Flying J`). A wrong link is worse than an honest centroid. The process must be offline,
cached and deterministic.

## Decision

- Fetch `amenity=fuel` per state from Overpass once, cached on disk.
- Clean names, then score with `rapidfuzz.fuzz.token_set_ratio`, taking the best of OSM `name` and `brand`.
- Consider only candidates within 15 mi of the centroid.
- Accept a match only at score ≥ 85 with a single top score.
- One OSM element maps to at most one station: the higher score wins; on a tie, the lower `opis_id`.

## Rejected alternatives

| Option | Why not |
| --- | --- |
| Exact name match | Store numbers and spelling variants break it |
| Levenshtein / plain ratio | Penalises extra brand words |
| Nearest station ignoring names | Exits often have several brands side by side |
| Address matching | OSM address tags are sparse; OPIS addresses are exits |
| Embeddings / LLM similarity | Non-deterministic and opaque |
| Per-request corridor query | A second external call; still no OPIS link |

## Consequences

- Precise coordinates for confident matches. Ties and weak scores never move a station.
- Deterministic and offline after the first fetch. `--skip-osm` keeps the baseline.
- Recall is incomplete, and the thresholds are judgement calls exposed in the report.
- Overpass is shared and rate-limited, which is why this feature is last and optional.
- ODbL attribution is required in the README.
