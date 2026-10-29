---

description: "Task list for Feature 001: Station Data Pipeline"
---

# Tasks: Station Data Pipeline

**Input**: Design documents from `specs/001-station-data-pipeline/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/build_station_data.md, quickstart.md

**Tests**: Required. Constitution IV (test-first, offline) and the plan's TDD order apply. Every test
task MUST be written and seen failing before its implementation task.

**Organization**: Tasks are grouped by user story. US1 (load offline) is checked against a small
hand-made fixture. The real shipped fixture is produced by US2's real run (T031).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1 / US2 / US3 from spec.md
- Paths are repo-relative (single Django project at the repo root)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Missing packages, output folders and shared test fixtures

- [X] T001 Create `tests/unit/stations/__init__.py` (empty), and create the output folders `data/places/` and `data/reports/`, each with a `.gitkeep`
- [X] T002 [P] Create `tests/fixtures/sample_fuel.csv`. Use the real header `OPIS Truckstop ID,Truckstop Name,Address,City,State,Rack ID,Retail Price` and about 20 rows covering:
  - 2 Canadian rows (`ON`, `QC`);
  - one ID with an exact duplicate row (same price);
  - one ID with 3 rows at different prices, one of them `3.00733333`;
  - one ID whose rows use different name spellings;
  - city values with trailing spaces;
  - the cities `St. Louis, MO`, `Mc Lean, IL` and `Ft Worth, TX`;
  - one city that exists in no gazetteer (`Nowhereville, KS`).
- [X] T003 [P] Create `tests/fixtures/sample_fuel_bad.csv`. Use the same header, with two malformed rows: line 3 has `Retail Price` `-3.1`; line 5 has an empty `City`. All other rows are valid.
- [X] T004 [P] Create `tests/fixtures/sample_geonames.txt`, about 10 tab-separated lines in the real 19-column `US.txt` format. Columns used: 0 geonameid, 1 name, 2 asciiname, 3 alternatenames, 4 lat, 5 lng, 6 feature class, 7 feature code, 10 admin1, 14 population. Include:
  - `Saint Louis, MO` (class P, population > 0);
  - `McLean, IL`;
  - `Fort Worth, TX`;
  - two `Springfield, IL` places with different populations (tie rule);
  - a third place with the same key and equal population but a higher geonameid;
  - one `PPLH` place that must be ignored;
  - one place matched only through its `alternatenames` column;
  - one class `P` place with population 0;
  - one non-`P` (e.g. class `H`) line.
- [X] T005 [P] Add shared pytest fixtures in `tests/conftest.py`: `fixtures_dir` (path to `tests/fixtures/`) and `out_dirs(tmp_path)`. `out_dirs` returns temp paths for the station fixture, the unmatched CSV and the place lookup, so integration tests never touch committed files.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The two models and their migration, needed by US1, US2 and US3

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T006 Write the failing test `tests/integration/test_models.py` (pytest-django, `@pytest.mark.django_db`). It covers:
  - saving a `FuelStation` and a `FuelPrice` with price `Decimal("3.00733333")` reads back `== Decimal("3.00733333")`;
  - `FuelStation.pk == opis_id`;
  - an explicitly set `FuelPrice.id` is kept;
  - deleting a station cascades to its prices.
- [X] T007 Implement the models in the `stations/models/` package (`fuel_station.py`, `fuel_price.py`, re-exported from `__init__.py`), exactly as in data-model.md:
  - **`FuelStation`:**
    - `opis_id = IntegerField(primary_key=True)`
    - `name = CharField(max_length=120)`
    - `address = CharField(max_length=200)`
    - `city = CharField(max_length=80)`
    - `state = CharField(max_length=2, db_index=True)`
    - `lat = FloatField(null=True)` and `lng = FloatField(null=True)`
    - `geo_source = CharField(max_length=20, choices=GeoSource.choices())`, where `GeoSource` is the `StrEnum` in `stations/enums.py` (`CITY_CENTROID = "city_centroid"`, `OSM = "osm"`; pure Python, no Django import; tested in `tests/unit/stations/test_enums.py`)
    - `match_score = PositiveSmallIntegerField(null=True)`
    - `best_price = DecimalField(max_digits=12, decimal_places=8)`
  - **`FuelPrice`:**
    - `station = ForeignKey(FuelStation, related_name="prices", on_delete=CASCADE)`
    - `rack_id = IntegerField()`
    - `raw_name = CharField(max_length=120)`
    - `price = DecimalField(max_digits=12, decimal_places=8)`
  - **No `Meta.ordering`** on either model (research R5).
- [X] T008 Generate `stations/migrations/0001_initial.py` with `python manage.py makemigrations stations`. Confirm T006 passes.
- [X] T009 [P] Register both models read-only in `stations/admin.py`: `list_display` (`opis_id`, `name`, `city`, `state`, `best_price`, `geo_source`), and search on name and city.

**Checkpoint**: the schema exists, and the exact-decimal round trip passes on SQLite.

---

## Phase 3: User Story 1 - Load ready-made station data offline (Priority: P1) 🎯 MVP

**Goal**: A reviewer loads the station data with one command, with no network and no gazetteer.

**Independent Test**: `python manage.py migrate && python manage.py loaddata <fixture>` on a fresh DB. The data is US-only, every station has coordinates with `geo_source = "city_centroid"`, and prices are exact.

### Tests for User Story 1 ⚠️ (write first, must fail)

- [X] T010 [P] [US1] Create the hand-made fixture `tests/fixtures/stations_sample.json` in Django `dumpdata` format (indent 2). It holds 3 `stations.fuelstation` objects (pk = opis_id, `geo_source` `city_centroid`, lat and lng set, prices as 8-dp strings) and 4 `stations.fuelprice` objects with explicit pks 1–4. One price is `"3.00733333"`.
- [X] T011 [US1] Write `tests/integration/test_load_stations.py`:
  - **Sample fixture:** `call_command("loaddata", <tests/fixtures/stations_sample.json>)` gives 3 stations and 4 prices.
  - **Shipped fields:** no state in the 13 Canadian codes; every station has non-null lat/lng and `geo_source == GeoSource.CITY_CENTROID`; `match_score is None`; the price reads back `== Decimal("3.00733333")`.
  - **Shipped fixture:** a second test loads `stations/fixtures/stations.json` with the same assertions plus `count() > 6000`. Use `pytest.mark.skipif(not path.exists())` until T031 produces it.

### Implementation for User Story 1

- [X] T012 [US1] Make T011 pass (models and migration from Phase 2; fix any fixture-format issue). Then add a "Load station data" note to the README Setup section in `README.md`: `python manage.py loaddata stations` (no network; arrives with the T031 data).

**Checkpoint**: loading works offline. The real `stations.json` arrives with US2 (T031), and T011's skipped test then runs.

---

## Phase 4: User Story 2 - Rebuild the station data with one command (Priority: P2)

**Goal**: `python manage.py build_station_data` validates the CSV, de-duplicates it, locates stations at city centres, stores them atomically, prints the report, and writes a byte-stable fixture and unmatched-cities file.

**Independent Test**: Run the command on the sample files and check the tables, the report and the outputs. Run it twice and get identical bytes and PKs. A bad CSV or a low match rate changes nothing (quickstart §2–3).

### Tests for User Story 2 ⚠️ (write first, must fail)

- [X] T013 [P] [US2] Write `tests/unit/stations/test_clean.py` (no DB) covering:
  - **Header:** exactly the 7 names after `strip()`. A missing or renamed column raises at once with `missing or renamed column: <name>`.
  - **Row reasons,** one test each, asserting `(line, column, value, reason)`:
    - ID and Rack ID: `missing` / `not an integer`;
    - price: `not a decimal` (also `NaN`, `Infinity`), `must be > 0`, `too precise` (more than 8 dp or more than 4 integer digits);
    - City and State: `missing`;
    - State: `unknown state code`;
    - the same ID with a different City or State: `conflicts with line <n>`.
  - **Error aggregation:** with 60 bad rows, the error lists 50 problems plus `… and 10 more (total 60)`.
  - **Not errors:** Canadian rows (13 codes) are dropped and counted, never reported as problems.
  - **Clean values:** values are stripped; prices are `Decimal` parsed from text (`Decimal("3.00733333")`).
  - **Line numbers:** `csv.DictReader.line_num`, with the header as line 1.
  - **`group_stations`:** one `StationRecord` per ID; `best_price == min(prices)`; name, address, city and state from the first row; all rows kept, in file order.
- [X] T014 [P] [US2] Write `tests/unit/stations/test_geonames.py` (no DB) covering:
  - **`normalise_place_name`:**
    - `"ST LOUIS "` → `"saint louis"`;
    - `"St. Louis"` → `"saint louis"`;
    - `"Ft Worth"` → `"fort worth"`;
    - `"Mt Vernon"` → `"mount vernon"`;
    - `"Ste Genevieve"` → `"sainte genevieve"`;
    - `"Mc Lean"` → `"mclean"`;
    - `"Winston-Salem"` → `"winston salem"`;
    - `"O'Fallon"` → `"ofallon"`;
    - internal runs of spaces are collapsed.
  - **`load_gazetteer(sample_geonames.txt)`:**
    - only class `P` is kept; `PPLH`, `PPLQ` and `PPLW` are skipped;
    - main keys come from name and asciiname;
    - alternate keys go in a separate dict;
    - tie rule: the higher population wins, then the lower geonameid;
    - lat/lng source text is preserved;
    - a missing file raises a clear error naming the path and `https://download.geonames.org/export/dump/US.zip`.
  - **Lookup:** the main name is tried first; the alternate name only when the main name misses (research R3).
- [X] T015 [P] [US2] Write `tests/unit/stations/test_build.py` (no DB) covering:
  - **`build()` on the sample files:**
    - located stations with `via` set to `primary` or `alternate`;
    - `Nowhereville, KS` is unmatched;
    - the counts behind the report: rows read, Canadian rows dropped, US price rows read, price rows stored (excluding unmatched stations' rows), stations kept, stations with several prices, located count and %, dropped count.
  - **`assign_price_ids()`:** ids 1..N ordered by `(opis_id, CSV line)`.
  - **`format_report()`:** the exact labels in contracts/build_station_data.md, including `Stations located N (P%, threshold T%)`.
- [X] T016 [P] [US2] Write `tests/unit/stations/test_export.py` (no DB), for `write_unmatched_csv()`:
  - header `opis_id,name,city,state`;
  - rows ordered by `opis_id`;
  - UTF-8 with `\n` line endings;
  - identical bytes on two writes;
  - written through a temp file and `os.replace` (no partial file left on error).
- [X] T017 [US2] Write `tests/integration/test_build_station_data.py` (pytest-django). Run `call_command("build_station_data", csv=…, geonames=…, plus the out_dirs overrides from T005)` on the samples and cover:
  - **(a) Happy path:** exit OK; stations, prices and best prices as expected; `geo_source == GeoSource.CITY_CENTROID`; `match_score` null; report labels on stdout; unmatched file lists `Nowhereville`.
  - **(b) Idempotence:** two runs give identical PKs and byte-identical fixture and unmatched files.
  - **(c) Precision:** after the run, `flush` then `loaddata` of the produced fixture still reads `Decimal("3.00733333")`.
  - **(d) Bad rows:** `sample_fuel_bad.csv` → `CommandError` naming lines 3 and 5. DB rows and output files are unchanged (pre-seed data, then compare).
  - **(e) Renamed header:** fails immediately; nothing written.
  - **(f) Below threshold:** `min_geocoded_pct` above the sample's share → `CommandError`; the report is printed and the unmatched file written; DB and fixture unchanged. The same sample with a lower `min_geocoded_pct` succeeds.
  - **(g) Missing gazetteer:** `CommandError` naming the path and download URL; nothing written.
  - **(h) `no_export=True`:** the DB is written but no fixture.
  - **(i) Skip OSM:** `skip_osm` is accepted and changes nothing.

### Implementation for User Story 2

- [X] T018 [P] [US2] Implement `stations/pipeline/clean.py` (no Django imports):
  - **Constants:** `EXPECTED_HEADER` (7 names); `US_STATE_CODES` (50 states + DC); `CANADIAN_CODES = {AB, BC, MB, NB, NL, NS, NT, NU, ON, PE, QC, SK, YT}`.
  - **Dataclasses:** `PriceRow(line, opis_id, name, address, city, state, rack_id, price: Decimal)` and `ValidationProblem(line, column, value, reason)`.
  - **Exception:** `CsvValidationError(problems, total)`, whose `__str__` gives the first 50 lines plus `… and N more (total T)`.
  - **Functions:**
    - `read_price_rows(path) -> (rows, canadian_count, rows_read)` validates the whole file first and raises on any problem (FR-020, research R8);
    - `group_stations(rows) -> list[StationRecord]`, sorted by `opis_id`.
- [X] T019 [P] [US2] Implement `stations/pipeline/geonames.py` (no Django imports):
  - **`normalise_place_name(s)`,** exactly FR-009: lower-case, strip; remove `.` and `'`; `-` → space; collapse spaces; token map `st→saint, ste→sainte, ft→fort, mt→mount`; join a `mc` token with the next one.
  - **`Place` dataclass:** `geonameid, name, state, lat_text, lng_text, population`.
  - **`load_gazetteer(path) -> Gazetteer(primary, alternate)`:**
    - stream with `str.split("\t")`;
    - class `P` only; skip `PPLH`, `PPLQ`, `PPLW`;
    - tie rule: population desc, then geonameid asc;
    - raise `GazetteerMissing` with the path and the download URL if the file is absent.
  - **`Gazetteer.lookup(city, state) -> (Place, "primary" | "alternate") | None`.**
- [X] T020 [US2] Implement `stations/pipeline/build.py` (no Django imports; depends on T018, T019):
  - **Dataclasses:** `LocatedStation`, and `BuildResult` (located, unmatched, all counts).
  - **`build(csv_path, geonames_path) -> BuildResult`.**
  - **`assign_price_ids(located) -> list[(id, opis_id, PriceRow)]`,** with ids 1..N ordered by `(opis_id, line)`.
  - **`located_pct(result)`.**
  - **`format_report(result, threshold, places_info=None) -> str`,** with the exact contract labels.
  - **Money rule:** no price arithmetic outside Python `Decimal`.
- [X] T021 [P] [US2] Implement `write_unmatched_csv(stations, path)` in `stations/pipeline/export.py` (no Django imports):
  - `csv.writer(lineterminator="\n")`, UTF-8;
  - rows ordered by `opis_id`;
  - write to `path.with_suffix(".tmp")`, then `os.replace`.
- [X] T022 [US2] Implement the rebuild **service** and a **thin** command (constitution, Technical Constraints: logic lives in services):
  - **Service, `stations/services/station_data.py`** (plus `stations/services/__init__.py`):
    - `rebuild_station_data(csv_path, geonames_path, *, min_geocoded_pct, export, fixture_out, unmatched_out, places_out) -> RebuildOutcome(result, report_text)`.
    - It owns the run phases, exactly as research R7:
      1. `build()`.
      2. Write the unmatched CSV.
      3. Threshold check → raise `LocatedShareTooLow(report_text)`.
      4. `transaction.atomic()`: delete all `FuelPrice` and `FuelStation`; `bulk_create` stations sorted by `opis_id` (lat/lng = `float(place.lat_text)`, `geo_source = GeoSource.CITY_CENTROID`); `bulk_create` prices with the explicit ids from `assign_price_ids`; `call_command("dumpdata", "stations.FuelStation", "stations.FuelPrice", indent=2, output=<temp>)`.
      5. After commit, `os.replace` the temp file onto `fixture_out`.
      6. On any exception, delete the temp files.
    - `CsvValidationError` and `GazetteerMissing` propagate unchanged. The service never prints.
  - **Command, `stations/management/commands/build_station_data.py`:** thin. It parses the flags, calls the service, writes `report_text` to stdout, and maps the service's exceptions to `CommandError` (non-zero exit). For `LocatedShareTooLow`, it prints the report first. Flags:
    - `--csv` (default `settings.FUEL_PRICES_CSV`);
    - `--geonames` (default `settings.GEONAMES_FILE`);
    - `--min-geocoded-pct` (float 0–100, default 95);
    - `--no-export`;
    - `--skip-osm` (accepted no-op);
    - hidden test-only output paths: `--fixture-out`, `--unmatched-out`, `--places-out`, defaulting to the committed paths.
- [X] T023 [US2] Run `python -m pytest tests/unit/stations tests/integration/test_build_station_data.py`. Fix until green. The test-first evidence is not checked here after the fact. Before each of T018–T022, the matching test file is run and its failing output (import or assertion errors) is shown, and that output is the record.

**Checkpoint**: the rebuild works on the samples, is reproducible, and fails safely.

---

## Phase 5: User Story 3 - Ship a place lookup for later "City, ST" input (Priority: P3)

**Goal**: The rebuild also writes the committed, byte-stable `data/places/us_places.csv.gz`. It has one row per `(normalised name, state)`, using the same rules as station matching.

**Independent Test**: After a sample rebuild, decompress the lookup:

- `("saint louis", "MO")` resolves to the same coordinates the St. Louis station got;
- there is exactly one row per key;
- the rows are ordered `(state, normalised_name)`;
- the bytes are identical on a second run.

### Tests for User Story 3 ⚠️ (write first, must fail)

- [X] T024 [P] [US3] Add place-lookup unit tests to `tests/unit/stations/test_build.py`. `place_index_rows(gazetteer, located)`:
  - includes every main-name place with population > 0, plus every place matched by a station (even with population 0);
  - adds an alternate-name row only for a place matched through an alternate name, and only when no main name already uses that `(normalised name, state)` key (research R3);
  - has exactly one row per key;
  - orders rows by `(state, normalised_name)`;
  - uses the columns `normalised_name, display_name, state, lat, lng, population`, with lat/lng as source text.
- [X] T025 [P] [US3] Add tests to `tests/unit/stations/test_export.py`. `write_places_gz(rows, path)`:
  - the gzip header has `mtime == 0` and no filename;
  - the content is a UTF-8 CSV with `\n` line endings;
  - two writes produce identical bytes;
  - writes go through a temp file and `os.replace`.
- [X] T026 [US3] Extend `tests/integration/test_build_station_data.py`:
  - a happy-path run also writes the place lookup;
  - the report includes `Places index N places, X.X MB`;
  - the lookup bytes are identical across two runs;
  - `no_export=True` writes no place lookup;
  - a threshold or validation failure leaves the lookup unchanged.

### Implementation for User Story 3

- [X] T027 [US3] Implement `place_index_rows(gazetteer, located) -> list[PlaceIndexRow]` in `stations/pipeline/build.py` (per T024). Add `places_index` to `BuildResult`.
- [X] T028 [P] [US3] Implement `write_places_gz(rows, path)` in `stations/pipeline/export.py`:
  - `gzip.GzipFile(filename="", mode="wb", fileobj=…, mtime=0)` wrapping a `csv.writer(lineterminator="\n")`;
  - write to a temp file, then `os.replace`.
- [X] T029 [US3] Wire the place lookup into the rebuild service `stations/services/station_data.py` (the command needs no change beyond printing the report):
  - write it to a temp file inside the atomic block (skipped with `--no-export`);
  - `os.replace` it onto `data/places/us_places.csv.gz` after commit;
  - pass `places_info` (count, MB) to `format_report`.
- [X] T030 [US3] Run `python -m pytest tests/unit/stations tests/integration`. Fix until green.

**Checkpoint**: all three stories work on the samples.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Real data run, shipped artifacts, docs and the final checks

- [X] T031 Run on the real data: `time python manage.py build_station_data`. Expected:
  - report: 8,151 rows read, 620 Canadian dropped, 7,531 US price rows read, 6,626 stations kept, 568 with several prices, about 99.8% located (threshold 95%), about 13 dropped (research R1);
  - commit `stations/fixtures/stations.json`, `data/reports/unmatched_cities.csv` and `data/places/us_places.csv.gz`;
  - record the rebuild time and the machine.
- [X] T032 Check reproducibility on the real data, per quickstart §2: `shasum` the three outputs, rebuild, `diff` → identical. Then `time python manage.py loaddata stations` on a fresh DB; record the load time.
- [X] T033 [P] Update `README.md`:
  - **Status:** mark 001 done.
  - **"Data and assumptions":** the real report numbers from T031 replace the "TBD after feature 001" text, along with the unmatched-cities file path and the threshold used (95%).
  - **Timings:** measured load and rebuild times with the machine (e.g. "Load: N s. Full rebuild: N s (2018 Intel MacBook Pro)").
  - **Setup:** add `python manage.py loaddata stations`.
  - **"Data attribution":** GeoNames, CC BY 4.0, because the committed place lookup redistributes GeoNames data.
  - **Rebuild instructions:** download `US.zip` to `data/geonames/`, then `python manage.py build_station_data`.
- [X] T034 [P] Sync `docs/implementation-plan.md` Feature 001 with the spec and plan (plan.md "Plan document sync"):
  - the unmatched-cities file is committed;
  - the conflicting city/state check;
  - the place-lookup ordering and the main-name-wins alternate rows;
  - `best_price` is computed in Python (no SQL price arithmetic).
- [X] T035 Run the coverage and quality gate:
  - `python -m pytest --cov=stations --cov-report=term-missing` → ≥ 90% on `stations/pipeline/`;
  - `ruff check .` and `ruff format --check .` clean;
  - `python manage.py check` clean.
- [X] T036 Run the quickstart.md validation end to end (§1–§4), including both failure paths. Confirm `git status` shows no changes after the failure runs.
  - A threshold failure rewrites `data/reports/unmatched_cities.csv` by design. It shows no change here only because the inputs, and so the bytes, are the same. A threshold test on the real data with different settings may change that one file, and that is expected.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies.
- **Foundational (Phase 2)**: depends on Setup. Blocks all stories.
- **US1 (Phase 3)**: depends on Phase 2. Its shipped-fixture test (T011, second test) stays skipped until T031.
- **US2 (Phase 4)**: depends on Phase 2.
- **US3 (Phase 5)**: depends on US2's `build.py` (T020) and command (T022), because it extends both.
- **Polish (Phase 6)**: depends on US1–US3.

### Within Each Story

- Tests first (they must fail), then pure modules, then the command, then the green run.
- T020 depends on T018 and T019. T022 depends on T020 and T021. T029 depends on T027, T028 and T022.

### Parallel Opportunities

- Setup: T002, T003, T004 and T005 run together after T001.
- Foundational: T009 runs alongside T008.
- US1: T010 runs alongside the US2 test writing.
- US2 tests: T013, T014, T015 and T016 run together (different files). T017 follows.
- US2 implementation: T018, T019 and T021 run together. T020 follows T018 and T019.
- US3: T024 and T025 run together. T028 runs alongside T027.
- Polish: T033 and T034 run together after T031 and T032.

---

## Parallel Example: User Story 2

```bash
# Tests first, all together:
Task: "Write tests/unit/stations/test_clean.py (T013)"
Task: "Write tests/unit/stations/test_geonames.py (T014)"
Task: "Write tests/unit/stations/test_build.py (T015)"
Task: "Write tests/unit/stations/test_export.py (T016)"

# Then the pure modules, together:
Task: "Implement stations/pipeline/clean.py (T018)"
Task: "Implement stations/pipeline/geonames.py (T019)"
Task: "Implement write_unmatched_csv in stations/pipeline/export.py (T021)"
```

---

## Implementation Strategy

### MVP First

1. Phase 1 and Phase 2: schema plus the exact-decimal guard.
2. Phase 3 (US1): offline loading is proven on the sample fixture.
3. Phase 4 (US2) and T031: the real shipped fixture exists. **This is the first point where a reviewer gets real station data.** In practice, the MVP is US1 + US2.
4. Phase 5 (US3): the place lookup, needed later by Feature 004.
5. Phase 6: README numbers, timings, attribution, plan sync, and the quality gate.

### Commit points

- After Phase 2: `feat(stations): models and migration`
- After US1: `test(stations): offline fixture loading`
- After US2: `feat(stations): build_station_data command`
- After US3: `feat(stations): place lookup export`
- After T031–T034: `data(stations): shipped station data, place lookup, unmatched report` and `docs: feature 001 results`

---

## Notes

- `[P]` means different files and no dependency on unfinished tasks.
- Pure modules under `stations/pipeline/` MUST NOT import Django (constitution III).
- No network anywhere in this feature. Integration tests write only to `tmp_path` (T005).
- Never assert timings in tests (SC-005 and SC-006 are measured by hand).
