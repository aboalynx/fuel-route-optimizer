# Quickstart: validating Feature 002

**Prerequisites:**
- Feature 001 is merged (station data available).
- The venv is installed from `requirements-dev.txt`.
- `python manage.py migrate && python manage.py loaddata stations` has been run for the manual checks.

## 1. Automated checks (offline)

```bash
python -m pytest tests/unit/routing tests/unit/planner tests/integration/test_index_loader.py
ruff check . && ruff format --check .
```

Expected: all pass, with no network access. respx fails any unmocked request.

What they prove:
- one call per route, even on errors (spec SC-001);
- every failure maps to "routing unavailable" with the right reason (SC-002);
- the 9.99 / 10.01 mi boundary, on-route = 0, and 0.05-mile mile markers (SC-003);
- stable ordering (SC-005);
- the index is built once, and an empty database raises `StationDataMissing`.

## 2. One real routing call (SC-006, needs the internet)

```bash
python manage.py shell -c "
from routing.base import LatLng
from routing.factory import provider_from_settings
r = provider_from_settings().route(LatLng(32.78, -96.80), LatLng(41.88, -87.63))
print(round(r.distance_miles, 1), len(r.points))"
```

Expected: about 966 miles and several thousand points (measured 966.5 mi, 9,149 points on
2026-10-29). Record the result in the README.

## 3. Candidates on the real route (manual)

```bash
python manage.py shell -c "
from routing.base import LatLng
from routing.factory import provider_from_settings
from planner.corridor import find_candidates
from stations.services.index_loader import get_station_index
r = provider_from_settings().route(LatLng(32.78, -96.80), LatLng(41.88, -87.63))
c = find_candidates(r, get_station_index(), 10)
print(len(c), c[0], c[-1])"
```

Expected: a few hundred candidates, mile markers rising from near 0 to near 966, and exact `Decimal`
prices.

## 4. Timing (SC-004, by hand)

Time `find_candidates` on a synthetic 3,000-mile route against the real index. The target is well
under 100 ms on a laptop. Record the figure and the machine in the README.
