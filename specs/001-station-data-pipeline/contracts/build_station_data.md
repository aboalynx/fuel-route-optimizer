# Contract: `python manage.py build_station_data`

## Arguments

| Flag | Default | Meaning |
| --- | --- | --- |
| `--csv PATH` | `settings.FUEL_PRICES_CSV` | Price file to read |
| `--geonames PATH` | `settings.GEONAMES_FILE` | GeoNames `US.txt` |
| `--min-geocoded-pct PCT` | `95` | Minimum located share, 0–100 (FR-021) |
| `--manual-coordinates PATH` | `data/overrides/manual_coordinates.csv` | Reviewed coordinates that win over lookup (FR-023). A missing file means no overrides |
| `--rejected-matches PATH` | `data/overrides/rejected_matches.csv` | Reviewed list of matches to reject (FR-022). A missing file means no rejections |
| `--no-export` | off | Store in the DB but do not write the fixture or the place lookup |

## Exit status

| Status | When | What is written |
| --- | --- | --- |
| 0 | Success | DB, `stations/fixtures/stations.json`, `data/places/us_places.csv.gz` (unless `--no-export`), `data/reports/unmatched_cities.csv` |
| non-zero | Missing or renamed header column, or malformed rows (FR-020) | Nothing |
| non-zero | Gazetteer file missing | Nothing |
| non-zero | Located share below `--min-geocoded-pct` (FR-021) | Only `data/reports/unmatched_cities.csv`, plus the report on stdout |

## Report (stdout, on success and on a threshold failure)

```text
Rows read 8,151 | Canadian rows dropped 620 | US price rows read 7,531 | price rows stored N
Stations kept 6,626 | with several prices 568
Stations located N (P%, threshold 95%) | city_centroid N (P%) | manual N (P%) | osm N (P%)
Stations dropped N (not found N, rejected match N) -> data/reports/unmatched_cities.csv
Places index N places, X.X MB
```

The exact wording is part of the contract. Tests match on these labels.

## Validation error (stderr, non-zero exit)

```text
Price file has 2 problem(s):
  line 14, Retail Price, '-3.1': must be > 0
  line 22, City, '': missing
```

If there are more than 50 problems, only the first 50 are listed, followed by
`… and N more (total T)`. A header problem prints a single line,
`missing or renamed column: Retail Price`, before any row is read.

## Output files

### `stations/fixtures/stations.json`

This is Django `dumpdata` output (indent 2) for `stations.FuelStation` and then
`stations.FuelPrice`, ordered by primary key. It loads with `python manage.py loaddata stations`.
Decimals are serialised as strings with 8 decimal places (e.g. `"3.00733333"`).

### `data/reports/unmatched_cities.csv`

UTF-8 with `\n` line endings, ordered by `opis_id`, committed. `reason` is `not found` or
`rejected match: <matched GeoNames name>`:

```text
opis_id,name,city,state,reason
```

### `data/overrides/manual_coordinates.csv` (input, committed, hand-reviewed)

```text
opis_id,lat,lng,source,note
```

Each row places one station at the given coordinates (`geo_source = manual`) and wins over the
gazetteer. `source` must be an openstreetmap.org URL. lat/lng must be inside the contiguous US
(lat 24 to 50, lng -125 to -66). A bad row stops the rebuild before anything is written, and the
error gives the line number.

### `data/overrides/rejected_matches.csv` (input, committed, hand-reviewed)

```text
city,state,matched_name,reason
```

It only rejects matches and never supplies coordinates. A malformed file stops the rebuild before
anything is written, and the error lists every problem.

### `data/places/us_places.csv.gz`

gzip with `mtime=0` and an empty filename. It holds a UTF-8 CSV with `\n` line endings, ordered by
`(state, normalised_name)`, with exactly one row per `(normalised_name, state)`. Committed.

```text
normalised_name,display_name,state,lat,lng,population
```

Rows included:
- every place with population > 0;
- every place matched by a station city;
- one row under the alternate name for each place matched through an alternate name, only if that key is not already a main-name key (research R3).

All three files are byte-for-byte identical across runs on the same inputs (SC-004).
