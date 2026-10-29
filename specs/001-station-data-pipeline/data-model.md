# Data Model: Station Data Pipeline (001)

## Stored entities (Django app `stations`)

### FuelStation

One physical US truck stop that was located.

| Field | Type | Rules |
| --- | --- | --- |
| `opis_id` | `IntegerField(primary_key=True)` | OPIS Truckstop ID; natural, stable key (R5) |
| `name` | `CharField(120)` | First name spelling in file order (FR-006) |
| `address` | `CharField(200)` | From the first row (FR-006) |
| `city` | `CharField(80)` | From the first row, trimmed, original casing |
| `state` | `CharField(2, db_index=True)` | US state or DC code |
| `lat`, `lng` | `FloatField(null=True)` | City-centre coordinates. Never null for stored stations in this feature |
| `geo_source` | `CharField(20, choices=GeoSource.choices())` | `GeoSource` `StrEnum` (`stations/enums.py`): `CITY_CENTROID = "city_centroid"`, `MANUAL = "manual"`, `OSM = "osm"`. `CITY_CENTROID` for a gazetteer match, `MANUAL` for a reviewed override (FR-023). Migration `0002` adds `manual` to the choices |
| `match_score` | `PositiveSmallIntegerField(null=True)` | Always null in 001; reserved for Feature 005 |
| `best_price` | `DecimalField(12, 8)` | Minimum of the station's price rows (FR-005), exact (FR-007) |

There is no `Meta.ordering`, so `dumpdata` orders by primary key (R5).

### FuelPrice

One raw US row of the price file, kept for traceability.

| Field | Type | Rules |
| --- | --- | --- |
| `id` | `BigAutoField` (project default), **set explicitly** | 1..N in order of `(opis_id, CSV line)` (R5) |
| `station` | `ForeignKey(FuelStation, related_name="prices", on_delete=CASCADE)` | Required. No price row exists without a station (FR-004) |
| `rack_id` | `IntegerField` | From the row |
| `raw_name` | `CharField(120)` | The name exactly as written on that row (trimmed) |
| `price` | `DecimalField(12, 8)` | Exact value from the file |

**Relationship:** each `FuelStation` has one or more `FuelPrice` rows (`prices`), and
`best_price == min(prices.price)`.

## In-memory records (pure pipeline, no Django)

| Record | Fields | Produced by |
| --- | --- | --- |
| `PriceRow` | `line: int`, `opis_id: int`, `name: str`, `address: str`, `city: str`, `state: str`, `rack_id: int`, `price: Decimal` | `clean.read_price_rows()` |
| `ValidationProblem` | `line: int`, `column: str`, `value: str`, `reason: str` | `clean.validate()` |
| `StationRecord` | `opis_id`, `name`, `address`, `city`, `state`, `best_price: Decimal`, `rows: list[PriceRow]` | `clean.group_stations()` |
| `Place` | `geonameid: int`, `name: str`, `state: str`, `lat_text: str`, `lng_text: str`, `population: int` | `geonames.load_gazetteer()` |
| `Gazetteer` | `primary: dict[(norm, state), Place]`, `alternate: dict[(norm, state), Place]` | `geonames.load_gazetteer()` |
| `LocatedStation` | `station: StationRecord`, `place: Place`, `via: MatchVia` (`PRIMARY`, `ALTERNATE`, `COMPACT`) | `build.build()` |
| `UnmatchedStation` | `station: StationRecord`, `reason: UnmatchedReason` (`NOT_FOUND` = "not found", `REJECTED` = "rejected match"), `matched_name: str \| None`; `reason_text` = "not found" or "rejected match: <matched_name>" | `build.build()` |
| `ManualCoordinate` | `line`, `opis_id: int`, `lat_text: str`, `lng_text: str` (stored exactly as written), `source: str` (openstreetmap.org URL), `note: str`, loaded from `data/overrides/manual_coordinates.csv` | `overrides.load_manual_coordinates()` |
| `RejectedMatches` | set of (normalised city, state, normalised matched name), loaded from `data/overrides/rejected_matches.csv` | `overrides.load_rejected_matches()` |
| `BuildResult` | `located: list[LocatedStation]`, `unmatched: list[UnmatchedStation]`, `canadian_rows: int`, `rows_read: int`, `places_index: list[PlaceIndexRow]` | `build.build()` |

## Lifecycle of one rebuild

```text
CSV ──validate──▶ problems? ──yes──▶ CommandError (nothing written)
  │ no
  ▼
group by opis_id ─▶ locate via Gazetteer ─▶ BuildResult
  ▼
print report + write data/reports/unmatched_cities.csv
  ▼
located share < threshold? ──yes──▶ CommandError (DB, fixture and place lookup untouched)
  │ no
  ▼
atomic: delete all → insert stations → assign price ids → insert prices → dump fixture/place lookup to temp files
  ▼
commit → os.replace temp files into place
```

## Validation rules (FR-020)

| Column | Rule | Reason text |
| --- | --- | --- |
| header | exactly the 7 expected names | `missing or renamed column: <name>` (fails immediately) |
| OPIS Truckstop ID | integer, required | `not an integer` / `missing` |
| Rack ID | integer, required | `not an integer` / `missing` |
| Retail Price | finite decimal, > 0, ≤ 8 decimals, ≤ 4 integer digits | `not a decimal` / `must be > 0` / `too precise` |
| City | non-empty after trim | `missing` |
| State | in US (50 + DC) or Canadian (13) codes | `unknown state code` |
| City/State per ID | same on every row of an ID | `conflicts with line <n>` |
