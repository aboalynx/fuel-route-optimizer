"""T011: the response body built from a plan result (precision, totals, shape)."""

from decimal import Decimal

import pytest

from api.presenters import present
from api.services.route_plan import FuelStop, RoutePlanResult, Vehicle
from planner.fewer_stops import FewerStopsResult
from planner.locations import ResolvedLocation
from planner.optimizer import PlanStation, plan_refuelling
from planner.station_index import StationInfo
from routing.base import LatLng, Route
from stations.enums import GeoSource

D = Decimal
VEHICLE = Vehicle(mpg=D(10), max_range_miles=D(500), capacity_gallons=D(50))


def info(opis_id, price):
    return StationInfo(
        opis_id, D(price), f"STATION {opis_id}", "I-30", "Town", "AR", GeoSource.CITY_CENTROID
    )


@pytest.fixture
def result():
    stations = [
        PlanStation(1, D("123.456"), D("3.00733333")),
        PlanStation(2, D("556.789"), D("2.81733333")),
    ]
    distance = D("966.452")
    plan = plan_refuelling(distance, stations, mpg=D(10), max_range_miles=D(500))
    by_id = {1: info(1, "3.00733333"), 2: info(2, "2.81733333")}
    stops = tuple(
        FuelStop(
            purchase=p,
            station=by_id[p.opis_id],
            lat=34.1234567,
            lng=-92.7654321,
            off_route_miles=1.23456,
        )
        for p in plan.purchases
    )
    return RoutePlanResult(
        start=ResolvedLocation("dallas, tx", 32.78306, -96.80667, "Dallas, TX"),
        finish=ResolvedLocation("41.88,-87.63", 41.88, -87.63, "Chicago, IL"),
        route=Route((LatLng(32.78, -96.8), LatLng(41.88, -87.63)), 966.4515, "osrm"),
        distance_miles=distance,
        vehicle=VEHICLE,
        start_fuel_gallons=D(50),
        corridor_miles=D(10),
        reserve_gallons=D(0),
        min_saving_per_stop_usd=D(0),
        plan=FewerStopsResult(plan=plan, cheapest=plan, stops_dropped=0),
        stops=stops,
        routing_calls=1,
        cached=False,
        candidates_count=2,
        timings_ms={"resolve": 1, "routing": 600, "candidates": 25, "optimize": 1, "total": 627},
    )


def places(value: Decimal) -> int:
    return -value.as_tuple().exponent


def test_top_level_shape(result):
    body = present(result)
    assert list(body) == ["start", "finish", "summary", "fuel_stops", "map", "meta"]
    assert body["start"] == {
        "query": "dallas, tx",
        "name": "Dallas, TX",
        "lat": 32.78306,
        "lng": -96.80667,
    }
    assert body["finish"]["name"] == "Chicago, IL"  # nearest place for coordinates


def test_summary_precision_and_totals(result):
    summary = present(result)["summary"]
    stops = present(result)["fuel_stops"]
    assert summary["distance_miles"] == D("966.452")
    assert summary["total_gallons_consumed"] == D("96.6452")
    assert places(summary["total_fuel_cost_usd"]) == 2
    assert summary["total_fuel_cost_usd"] == sum(s["cost_usd"] for s in stops)
    assert places(summary["gallons_purchased"]) == 4
    assert places(summary["fuel_left_gallons"]) == 4
    assert summary["stops_count"] == len(stops)
    assert summary["stops_dropped"] == 0
    assert summary["extra_cost_vs_cheapest_usd"] == D("0.00")
    assert summary["assumptions"] == {
        "mpg": D(10),
        "max_range_miles": D(500),
        "tank_capacity_gallons": D(50),
        "start_fuel_gallons": D(50),
        "corridor_miles": D(10),
        "reserve_gallons": D(0),
        "min_saving_per_stop_usd": D(0),
    }


def test_each_stop_has_the_contract_fields_and_adds_up(result):
    stops = present(result)["fuel_stops"]
    assert [s["sequence"] for s in stops] == list(range(1, len(stops) + 1))
    for stop in stops:
        assert list(stop) == [
            "sequence",
            "opis_id",
            "name",
            "address",
            "city",
            "state",
            "lat",
            "lng",
            "geo_source",
            "mile_marker",
            "off_route_miles",
            "price_usd_per_gallon",
            "gallons",
            "cost_usd",
        ]
        assert places(stop["gallons"]) == 4
        assert places(stop["cost_usd"]) == 2
        assert stop["price_usd_per_gallon"] in (D("3.00733333"), D("2.81733333"))  # exact
        assert places(stop["mile_marker"]) == 3
        assert stop["off_route_miles"] == 1.235
        assert stop["geo_source"] == "city_centroid"
        assert abs(stop["gallons"] * stop["price_usd_per_gallon"] - stop["cost_usd"]) <= D("0.005")


def test_map_and_meta(result):
    body = present(result)
    features = body["map"]["features"]
    assert features[0]["properties"] == {"kind": "route"}
    assert [f["properties"]["sequence"] for f in features[1:]] == [
        s["sequence"] for s in body["fuel_stops"]
    ]
    assert body["meta"] == {
        "routing_provider": "osrm",
        "routing_calls": 1,
        "cached": False,
        "candidate_stations_considered": 2,
        "timings_ms": {"resolve": 1, "routing": 600, "candidates": 25, "optimize": 1, "total": 627},
    }
