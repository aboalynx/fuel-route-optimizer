# Quickstart: validating Feature 001

**Prerequisites:**
- Phase 0 is done: `requirements-dev.txt` and CI exist.
- Python: Python 3.13–3.14 officially (Django 6.1.2); also developed and CI-tested on 3.15. Django adds official 3.15 support in 6.1.3.
- For the rebuild scenarios only: `data/geonames/US.txt` has been downloaded from
  `https://download.geonames.org/export/dump/US.zip` and unzipped.

## 1. Reviewer path: load the shipped data (User Story 1, SC-005)

```bash
python manage.py migrate
time python manage.py loaddata stations       # no network needed; record the time in the README
python manage.py shell -c "from stations.models import FuelStation as S; print(S.objects.count(), S.objects.filter(state__in=['ON','QC','AB']).count())"
```

Expected: 6,618 stations, 0 Canadian, and a load time well under 1 minute.

## 2. Maintainer path: rebuild (User Story 2, SC-001–SC-004, SC-006)

```bash
time python manage.py build_station_data      # record the time in the README
```

Expected report: 8,151 rows read, 620 Canadian dropped, 7,531 US price rows read, 6,626 stations
kept, 568 with several prices, 99.9% located (threshold 95%), and 8 dropped (6 not found, 2 rejected match). The
numbers come from the research feasibility scan (R1). See [contracts/build_station_data.md](contracts/build_station_data.md)
for the exact format.

Check that the outputs are reproducible (SC-004):

```bash
shasum stations/fixtures/stations.json data/places/us_places.csv.gz data/reports/unmatched_cities.csv > /tmp/a
python manage.py build_station_data
shasum stations/fixtures/stations.json data/places/us_places.csv.gz data/reports/unmatched_cities.csv | diff - /tmp/a && echo identical
```

## 3. Failure paths (FR-020, FR-021)

```bash
python manage.py build_station_data --csv tests/fixtures/sample_fuel_bad.csv; echo "exit $?"
# expect: non-zero exit, both bad line numbers listed, git status shows no changed files

python manage.py build_station_data --min-geocoded-pct 99.9; echo "exit $?"
# expect: non-zero exit, report printed, fixture and place lookup unchanged
```

## 4. Automated checks

```bash
python -m pytest tests/unit/stations tests/integration/test_build_station_data.py
ruff check . && ruff format --check .
```

All of these tests run offline and use the small samples in `tests/fixtures/`.
