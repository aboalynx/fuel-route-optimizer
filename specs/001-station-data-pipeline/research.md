# Research: Station Data Pipeline (001)

Every decision below is final for this feature, and no NEEDS CLARIFICATION items remain. Numbers
marked *measured* come from a read-only feasibility scan of the real `data/geonames/US.txt` and
`data/fuel-prices-for-be-assessment.csv`, run on the developer's laptop on 2026-10-29.

## R1. Feasibility of city-centre matching (SC-002)

- **Decision:** match on exact normalised `(name, state)` keys. Main names come first, and alternate names are only a fallback. There is no fuzzy matching tier.
- **Measured:**
  - 6,626 stations;
  - 6,597 matched by main name and 16 by alternate name, so **99.8% located**;
  - **13 unmatched**: `De Forest, WI` ×4, `Willow Beach, AZ` ×3, and one each of `Bois D Arc, MO`, `Pueblo Of Acoma, NM`, `Brookpark, OH`, `Crescent, PA`, `S Coffeyville, OK`, `Corinth, ME`.
- **Rationale:** 99.8% is well above the 95% threshold. A fuzzy tier would add guessing (constitution I) for at most 13 stations.
- **Alternatives considered:** a rapidfuzz fallback within the state (rejected: non-obvious matches, extra rules to explain). Ignoring spaces when comparing names (`De Forest` ↔ `DeForest`) would recover 4 stations. It is left as future work, so FR-009 stays exactly as specified.

## R2. Gazetteer parsing

- **Decision:** stream `US.txt` line by line with `str.split("\t")`. Do not use the `csv` module.
- **Filters:**
  - keep feature class `P` only;
  - skip feature codes `PPLH`, `PPLQ`, `PPLW`;
  - read columns 0, 1, 2, 3, 4, 5, 6, 7, 10, 14.
- **Measured:** full scan 6.5 s; 183,981 class-P places kept; 168,920 main-name keys; 363,016 alternate-name keys.
- **Rationale:** GeoNames is tab-separated with no quoting, and names can contain `"` characters. `csv` with its default quoting would mis-split those lines, and `split` is also faster.
- **Coordinates:** latitude and longitude are kept as the **source text** for the place lookup (byte-stable) and parsed with `float()` for storage.

## R3. Tie rule and the main-name vs alternate-name collision (FR-010, FR-016)

- **Decision (confirmed 2026-10-29):**
  - One winner per key: the highest population, then the lowest geonameid.
  - The main-name index and the alternate-name index are built separately.
  - A **main name always wins**. An alternate-name row is added to the place lookup only when no main name already uses that `(normalised name, state)` key, and only for a place a station was matched through.
- **Measured:** 58,288 alternate keys collide with a main-name key, so the conflict is real.
- **Rationale:** this keeps "exactly one row per (normalised name, state)" (FR-016). It also mirrors station matching, where the alternate name is used only when the main name misses, so `"City, ST"` lookups resolve exactly as station matching did.
- **Status:** confirmed.

## R4. Price precision and SQLite (FR-007, SC-003)

- **Decision:** `DecimalField(max_digits=12, decimal_places=8)` for `FuelPrice.price` and `FuelStation.best_price`. Parse with `Decimal(raw_text)`.
- **Validation:** reject values that are not finite (`NaN`, `Infinity`), have more than 8 decimals, or have more than 4 integer digits. These are malformed under FR-020, because they could not be stored exactly (FR-007).
- **Rationale:**
  - Django's SQLite backend stores decimals with NUMERIC affinity, as REAL when the value fits.
  - On read, the converter rebuilds a `Decimal` with 15-digit precision and quantizes it to 8 places.
  - With at most 12 significant digits, every value round-trips exactly. `3.00733333` → `Decimal("3.00733333")`.
  - On PostgreSQL the column is a true `numeric(12,8)`.
- **Constraint:** no price arithmetic in SQL. SQLite holds the value as a float, and only Django's read converter makes it exact again. So `Min`/`Sum` aggregates or comparisons inside SQLite could run on floats. Prices are compared and summed only as Python `Decimal`, and `best_price` is computed in the pipeline. The `3.00733333` round-trip test stays as the guard.
- **Alternatives considered:** storing prices as integer micro-dollars (rejected: an unfamiliar unit, and conversions everywhere) or as text (rejected: loses DB-level numeric meaning).

## R5. Stable identifiers and ordering (FR-013, FR-014, SC-004)

- **Decision:**
  - `FuelStation.opis_id` is the primary key.
  - `FuelPrice.id` is assigned explicitly as 1..N, in order of `opis_id` and then CSV line number.
  - Neither model sets `Meta.ordering`. Django's `dumpdata` then orders each model by primary key, which gives the fixture a stable order without extra code.
- **Rationale:** after a delete, SQLite AUTOINCREMENT and PostgreSQL sequences hand out new ids, which would change the fixture between runs.
- **Fixture output:** `call_command("dumpdata", "stations.FuelStation", "stations.FuelPrice", indent=2, output=tmp)`.

## R6. Byte-stable place lookup (FR-014)

- **Decision:**
  - Write the rows with `csv.writer(lineterminator="\n")`.
  - Order by `(state, normalised_name)`.
  - Compress with `gzip.GzipFile(filename="", mtime=0)`.
- **Rationale:** the gzip header contains a timestamp and the original filename. Fixing both makes the compressed bytes depend only on the content.
- **Measured size driver:** 31,712 places have population > 0, plus about 1–2k places matched by stations. A few hundred KB compressed is expected, far under the 10 MB in SC-007.

## R7. Atomic writes: nothing changes on failure (FR-020, FR-021)

- **Decision:** run in phases.
  1. **Validate** the whole CSV and collect every problem. On any problem, raise `CommandError` (non-zero exit). Nothing has been touched.
  2. **Build in memory:** group, locate, and compute the report and the unmatched list.
  3. **Report and unmatched file:** print the report and write `data/reports/unmatched_cities.csv` (temp file + `os.replace`). This is the only output written when the threshold fails.
  4. **Threshold check:** if the located share is below `--min-geocoded-pct`, raise `CommandError`. The DB, fixture and place lookup are untouched.
  5. **Store and export:** inside `transaction.atomic()`, delete and insert the rows, then dump the fixture and write the place lookup to temp files on the same connection. If anything fails, the transaction rolls back and the temp files are deleted. Only after a successful commit does `os.replace` swap the temp files into place.
- **Rationale:** every failure path leaves the stored data and the shipped files exactly as they were.

## R8. Validation details (FR-020)

- **Line numbers:** `csv.DictReader.line_num`. The header is line 1.
- **Header check:** compare the exact header list with the 7 expected names after `strip()`. A missing or renamed column fails immediately, before any row is read.
- **Row checks:**
  - ID or Rack ID missing, or not an integer (`int()` after strip; no signs or decimals allowed);
  - price invalid or ≤ 0 (R4);
  - empty City or State;
  - State not in the 51 US codes (50 states + DC) and not in the 13 Canadian codes;
  - the same ID appears with a different City or State. Both line numbers are reported.
- **Error output:** the first 50 problems, then `… and N more (total T)`.

## R9. Command interface

- **Decision:** Django management command `build_station_data` with these flags:
  - `--csv`
  - `--geonames`
  - `--min-geocoded-pct` (float, default 95, range 0–100)
  - `--no-export`
  - `--skip-osm`: accepted but a no-op in this feature. It is the only behaviour until Feature 005, and accepting it now keeps the command contract stable.
- **Missing gazetteer:** `CommandError` naming the expected path and the download URL (`https://download.geonames.org/export/dump/US.zip`).
- **Rationale:** this is the standard Django entry point, so a reviewer finds it with `python manage.py help`.

## R10. Testing approach (constitution IV)

- **Unit tests (no DB):** CSV validation and grouping, `normalise_place_name`, the gazetteer index, the tie rule, the alternate-name fallback, and place-lookup bytes.
- **Integration tests (pytest-django, `tmp_path` for outputs):**
  - an end-to-end run on `tests/fixtures/sample_fuel.csv` and `tests/fixtures/sample_geonames.txt`;
  - two runs giving byte-identical outputs and identical primary keys;
  - `3.00733333` surviving a fixture round-trip through `loaddata`;
  - two bad rows → non-zero exit with both line numbers, and the DB unchanged;
  - below the threshold → DB and fixture unchanged, then a pass with a lower threshold;
  - a missing gazetteer.
- **No network:** nothing in this feature uses the network, so no mocks are needed.
- **Timings (SC-005, SC-006):** measured once by hand and recorded in the README, not asserted in CI.
