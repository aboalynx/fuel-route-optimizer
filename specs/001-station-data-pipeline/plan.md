# Implementation Plan: Station Data Pipeline

**Branch**: `001-station-data-pipeline` | **Date**: 2026-10-29 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-station-data-pipeline/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

A single Django management command, `build_station_data`, rebuilds the station data set. It runs in this order:

1. Validate the whole OPIS price CSV.
2. Drop the Canadian rows.
3. Group the rows by OPIS ID, using the minimum price and the first row's identity.
4. Locate each station at its city centre, using an offline GeoNames index with one normalisation rule.
5. Store everything atomically in `FuelStation` / `FuelPrice`.
6. Export three committed, byte-stable files: the Django fixture, the unmatched-cities CSV, and the gzipped place lookup.

The logic lives in pure modules under `stations/pipeline/`, and the command is a thin shell around them. A
feasibility scan of the real files measured 99.8% of stations located (13 unmatched) and a
6.5 s gazetteer pass (research R1, R2).

## Technical Context

**Language/Version**: Python 3.15 (venv 3.15.2). Supported range: Python 3.13–3.14 officially (Django 6.1.2); also developed and CI-tested on 3.15. Django adds official 3.15 support in 6.1.3.

**Primary Dependencies**: Django 6.1.2 (on Python 3.15; supported range above), django-environ. The standard library covers `csv`, `decimal`, `gzip` and `dataclasses`. This feature needs no numpy, scipy, rapidfuzz or httpx.

**Storage**: SQLite by default (`DATABASE_URL`), with two tables. Committed files: `stations/fixtures/stations.json`, `data/reports/unmatched_cities.csv`, `data/places/us_places.csv.gz`.

**Testing**: pytest + pytest-django, with small fixtures in `tests/fixtures/`. Offline only.

**Target Platform**: Developer laptop and CI (Linux runner). The rebuild runs only where `US.txt` is present, so not in CI.

**Project Type**: Web service (Django). This feature is an offline data pipeline exposed as a management command.

**Performance Goals**: load < 1 min, rebuild < 5 min, both measured by hand (SC-005, SC-006). The measured gazetteer pass is 6.5 s.

**Constraints**:

- no network;
- exact decimals (12, 8);
- no price arithmetic in SQL. SQLite stores decimals as floats and Django quantizes on read, so prices are compared and summed only as Python `Decimal`. `best_price` is computed in the pipeline, not with an aggregate. The `3.00733333` round-trip test stays;
- byte-identical outputs across runs;
- nothing written on a validation failure;
- only the unmatched file written on a threshold failure.

**Scale/Scope**: 8,151 CSV rows, 6,626 stations, 7,531 price rows, 183,981 gazetteer places scanned, about 32–34k places in the lookup.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Check | Status |
| --- | --- | --- |
| I. Deterministic Results | Total tie rule (population, then geonameid), explicit ids, fixed output order, gzip `mtime=0` (R3, R5, R6) | Pass |
| II. Single External Routing Call | No routing and no network in this feature | Pass (N/A) |
| III. Pure Core | `stations/pipeline/*` has no Django imports. The command only does I/O, the DB and the report | Pass |
| IV. Test-First, Offline Tests | Unit and integration tests are written first, and no network is involved. **Prerequisite:** the Phase 0 CI workflow must exist so that "green in CI" can be met | Pass, conditional on Phase 0 |
| V. Explicit Units and Decimal Money | `Decimal` parsed from text, `DecimalField(12, 8)`, no rounding in this feature (R4) | Pass |
| VI. Documented Data Assumptions | The README update (Canada excluded, minimum price, city centroids, report numbers, threshold) ships with this feature | Pass |
| VII. Simplicity Over Cleverness | Standard library plus Django `dumpdata`/`loaddata`; no fuzzy tier, cache or extra service | Pass |
| VIII. Zero-Setup Reviewer Run | The fixture and place lookup are committed. `loaddata` needs no network and no `US.txt` | Pass |

**Post-design re-check (after Phase 1):** all gates still pass. The design adds no dependency and
no infrastructure. R3 is confirmed: a main name always wins in the place lookup.

## Project Structure

### Documentation (this feature)

```text
specs/001-station-data-pipeline/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   └── build_station_data.md
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 output (/speckit-tasks; not created here)
```

### Source Code (repository root)

```text
stations/
├── models.py                       # FuelStation, FuelPrice
├── migrations/0001_initial.py
├── pipeline/                       # pure, no Django imports
│   ├── __init__.py
│   ├── clean.py                    # header check, row validation, PriceRow, group_stations
│   ├── geonames.py                 # normalise_place_name, load_gazetteer, tie rule, lookup
│   ├── build.py                    # locate stations, BuildResult, report numbers, place-lookup rows
│   └── export.py                   # byte-stable writers: unmatched CSV, gzipped place lookup
├── management/commands/
│   └── build_station_data.py       # flags, phases R7, DB write, dumpdata, report output
└── fixtures/stations.json          # committed

data/
├── places/us_places.csv.gz         # committed
└── reports/unmatched_cities.csv    # committed

tests/
├── fixtures/
│   ├── sample_fuel.csv             # ~20 rows: Canada, duplicates, spelling variants, spaces, St./Mc/Ft, unknown city, 3.00733333
│   ├── sample_fuel_bad.csv         # two malformed rows
│   └── sample_geonames.txt         # ~10 lines in US.txt format: a tie, a PPLH place, an alternate name
├── unit/
│   ├── __init__.py
│   └── stations/
│       ├── __init__.py
│       ├── test_clean.py
│       ├── test_geonames.py
│       ├── test_build.py
│       └── test_export.py
└── integration/
    └── test_build_station_data.py
```

**Structure Decision**: keep the existing single Django project. This feature touches only the
`stations` app, `data/`, and `tests/`. The pipeline is split into four small pure modules (one per
concern), so each has its own unit test file and the management command stays thin.

## Implementation notes for `/speckit-tasks`

- **Order (TDD):**
  1. sample fixtures;
  2. `clean` tests, then `clean`;
  3. `geonames` tests, then `geonames`;
  4. `build` tests, then `build`;
  5. `export` tests, then `export`;
  6. models and migration;
  7. command integration tests, then the command;
  8. a real run, committing the fixture, place lookup and unmatched file;
  9. The README: report numbers, timings, assumptions, and the **GeoNames attribution (CC BY 4.0)**. The attribution is required because the committed place lookup redistributes GeoNames data.
- **Command phases:** follow research R7 exactly, so that failure leaves the DB and files unchanged.
- **Plan document sync:** `docs/implementation-plan.md` Feature 001 should mention the committed unmatched file, the conflicting city/state check and the place-lookup ordering and alternate rows. Do this in the same change as the code.

## Complexity Tracking

No constitution violations. Nothing to justify.
