# ADR-0003: Offline GeoNames city-centroid geocoding

- Status: Accepted · Date: 2026-10-29
- Related: [station-geocoding.md](../algorithms/station-geocoding.md), Feature 001 (and 004 for input lookup), F1/F6/N3/N4/D5/D9

## Context

The price CSV has no coordinates, and many addresses are highway exits. The same capability is
needed at request time to resolve `"City, ST"` without spending the single external call.

The reviewer must run everything with no keys and no geocoding step (constitution VIII).

## Decision

- Match each station's (city, state) offline against GeoNames US populated places:
  - one `normalise_place_name()` (st → saint, ft → fort, mt → mount, ste → sainte, Mc joining);
  - feature class P, excluding PPLH/PPLQ/PPLW;
  - primary names first, alternate names only as a fallback;
  - ties broken by population, then geonameid.
- Stations get `geo_source = GeoSource.CITY_CENTROID`. Unmatched stations are excluded and listed in
  `data/reports/unmatched_cities.csv`.
- Export a committed places index (`data/places/us_places.csv.gz`) so request-time lookups use the
  same normalisation.

## Rejected alternatives

| Option | Why not |
| --- | --- |
| Nominatim per station | Policy discourages bulk use; ~2 h at 1 req/s; weak on exit addresses |
| US Census batch geocoder | Address-based; weak on highway exits; an external step |
| Google / Mapbox / HERE | Keys, billing, storage restrictions |
| Geocoding per request | Extra external calls (violates the one-call rule) |
| LLM-generated coordinates | Unverifiable and non-deterministic |

## Consequences

- Zero network at request time and in tests. One normalisation serves both stations and user input.
- Byte-identical re-runs require stable keys. `opis_id` is the station primary key, and `FuelPrice.id` is assigned explicitly as 1..N (by `opis_id`, then CSV row order), because SQLite AUTOINCREMENT and PostgreSQL sequences give new ids after a delete.
- Several miles of positional error. The corridor radius mitigates it; exact coordinates are future work (README, "Station coordinates: current approach and production path"; one design is ADR-0004).
- A few cities go unmatched (target ≥ 95% geocoded).
- The "in the USA" check for coordinates is approximate (nearest place within 25 mi).
- `US.txt` is not committed. Only pipeline re-runs need it.
