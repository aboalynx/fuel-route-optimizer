# Algorithm: offline station geocoding with GeoNames city centroids

Modules `stations/pipeline/clean.py`, `stations/pipeline/geonames.py`, `planner/locations.py` · Feature 001 (lookup reused by 004) · [ADR-0003](../adr/0003-offline-centroid-geocoding.md)

## Context

The CSV has no coordinates. Its addresses are often highway exits that street geocoders handle
poorly. The data covers 6,626 US stations in 3,808 (city, state) pairs. Geocoding must be:

- offline;
- deterministic;
- reusable at request time for `"City, ST"` input.

## Decision

The full step list is in [Feature 001](../implementation-plan.md#feature-001-station-data-pipeline). The algorithmic core:

```text
normalise_place_name(s):
    lower-case, strip; remove "." and "'"; "-" -> " "; collapse spaces
    token map: st -> saint, ste -> sainte, ft -> fort, mt -> mount
    join a "mc" token with the next one ("mc lean" -> "mclean")

gazetteer = US.txt rows with feature class P, excluding PPLH / PPLQ / PPLW
primary   = {(norm(name), state), (norm(asciiname), state)} -> place
fallback  = {(norm(alt), state) for alt in alternatenames}  -> place   # only if primary misses
compact   = {(compact(name), state)} from main names only     -> place   # only if both miss
            compact(s) = norm(s), leading n/s/e/w -> north/south/east/west, all spaces removed
tie rule  = highest population, then lowest geonameid

for each station: place = primary.get(key) or fallback.get(key) or compact.get(ckey)
    found   -> lat, lng = place centroid; geo_source = GeoSource.CITY_CENTROID; match_score = null
    missing -> excluded, written to data/reports/unmatched_cities.csv
```

The same `normalise_place_name` builds the committed places index `data/places/us_places.csv.gz`
(class P with population > 0, plus every station-matched place). `planner/locations.py` uses it
to resolve `"City, ST"`. Coordinates count as "in the USA" when the nearest place is within 25 miles.

Alternate names are only a fallback, because they include foreign and historical names that would
cause false matches if used first. The compact tier comes last and catches spacing, punctuation and
direction-abbreviation differences ("De Forest" vs "DeForest", "S Coffeyville" vs "South
Coffeyville"). It is still an exact key, so matching stays deterministic.

## Rejected alternatives

- Nominatim per station: the policy discourages bulk use, ~2 h at 1 req/s, and it is poor on exit addresses.
- US Census batch geocoder: address-based, so it is weak on highway exits.
- Google/Mapbox: needs keys, and the licence limits storing results.
- Geocoding per request: breaks the one-call rule.
- LLM-generated coordinates: unverifiable.

## Consequences

- No network at request time or in tests.
- Reproducible output: the command re-runs to a byte-identical fixture.
- One normalisation serves both stations and user input.
- Accuracy is the city centroid. The corridor radius and the optional OSM layer compensate.
- Large cities collapse many stations onto one point.
- A few cities go unmatched. They are listed for review, and the target is ≥ 95% geocoded.
