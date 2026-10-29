# Algorithm: OSM precision layer (fuzzy name matching)

Modules `stations/pipeline/osm.py`, `stations/pipeline/matching.py` · Feature 005 (stretch) · [ADR-0004](../adr/0004-osm-fuzzy-name-matching.md)

## Context

City centroids can be miles from the real station. OpenStreetMap has exact `amenity=fuel` points,
but no OPIS IDs, so the two can only be linked by name and proximity. A wrong link is worse than an
honest centroid. Everything runs offline in `build_station_data`.

## Decision

```text
fetch:  one Overpass query per state
            area["ISO3166-2"="US-XX"]; node+way["amenity"="fuel"]; out center tags
        POST https://overpass-api.de/api/interpreter, timeout 200 s, one at a time, pause between
        cache -> data/cache/osm/<STATE>.json; if present, no request is made

clean(s): lower-case; remove store numbers ("#1243"); remove generic words
          (travel center(s), travel plaza, truck stop, dba); collapse spaces

for station in stations (by opis_id):
    cands  = OSM elements within 15 mi of the city centroid   (cKDTree on 3D unit vectors)
    score  = max(token_set_ratio(clean(name), clean(osm.name)),
                 token_set_ratio(clean(name), clean(osm.brand)))
    accept the top candidate if score >= 85 and it is the single best score; a tie keeps the centroid

de-conflict: one OSM element -> at most one station; higher score wins, tie -> lower opis_id;
             the loser keeps its centroid
apply:       lat/lng from OSM, geo_source = "osm", match_score = score
```

`token_set_ratio` ignores word order and extra words: `pilot` vs `pilot flying j` scores 100. The
`brand` tag is often cleaner than `name`. The radius (15 mi) and threshold (85) are module
constants, and the report shows their effect (osm / city_centroid / dropped percentages).

## Rejected alternatives

- Exact name match: store numbers and spelling variants break it.
- Plain Levenshtein: penalises the extra brand words.
- Nearest station ignoring names: truck exits have several brands side by side.
- Address matching: OSM address tags are sparse.
- Embeddings or an LLM: non-deterministic.
- A per-request corridor query: a second external call.

## Consequences

- Precise coordinates for confident matches.
- Ties and weak scores never move a station, so precision is chosen over recall.
- Deterministic, and network-free after the first fetch. Tests use a saved Overpass sample.
- Optional: `--skip-osm` keeps the baseline.
- Recall is incomplete, and the thresholds are judgement calls.
- OSM data is ODbL, so the README must attribute it.
