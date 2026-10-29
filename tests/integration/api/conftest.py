"""Shared fixtures for the route-plan API tests (no network: respx mocks OSRM).

tests/fixtures/stations_route_plan.json places stations exactly on points of the recorded
Dallas -> Chicago geometry (tests/fixtures/osrm_dallas_chicago.json):

- pk 101 at geometry index 8 ($3.10, mile ~125), pk 102 at index 16 ($2.95, mile ~319),
  pk 103 at index 24 ($3.25, mile ~521), pk 104 at index 36 ($2.90, mile ~756);
- pk 105 is index 20 moved 30 mi east ($1.00): outside the 10-mile corridor, never a candidate.

The recorded fixture keeps ~50 of the real route's points, so its geometry (919 mi) is shorter
than its distance (966 mi) and find_candidates logs its mile-marker scaling WARNING on every API
test. That is expected: one test in test_route_plan_api.py asserts it once; the others ignore it.
"""

import json
from pathlib import Path

import httpx
import pytest
from django.conf import settings
from django.core.cache import cache
from django.core.management import call_command

from api.services.places import get_place_index
from stations.services.index_loader import get_station_index

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
ROUTE_JSON = json.loads((FIXTURES / "osrm_dallas_chicago.json").read_text())
API_URL = "/api/v1/route-plan/"


@pytest.fixture(autouse=True)
def fresh_state():
    """Every test starts with an empty route cache and freshly built indexes."""
    cache.clear()
    get_station_index.cache_clear()
    get_place_index.cache_clear()
    yield
    cache.clear()
    get_station_index.cache_clear()
    get_place_index.cache_clear()


@pytest.fixture
def route_stations(db):
    call_command("loaddata", str(FIXTURES / "stations_route_plan.json"), verbosity=0)


@pytest.fixture
def osrm(respx_mock):
    """Every OSRM route request answers with the recorded Dallas -> Chicago response."""
    return respx_mock.get(url__startswith=f"{settings.OSRM_BASE_URL}/route/v1/driving/").mock(
        return_value=httpx.Response(200, json=ROUTE_JSON)
    )


def osrm_route(points, distance_meters):
    """An OSRM response for a hand-made route; points are (lat, lng)."""
    return {
        "code": "Ok",
        "routes": [
            {
                "distance": distance_meters,
                "geometry": {"type": "LineString", "coordinates": [[g, t] for t, g in points]},
            }
        ],
        "waypoints": [{"distance": 1.0, "location": [points[0][1], points[0][0]], "name": ""}],
    }


def post(client, body):
    return client.post(API_URL, body, content_type="application/json")
