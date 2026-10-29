"""T007: impossible trips raise InfeasibleRoute with the reason, the gap and the details."""

from decimal import Decimal

import pytest

from planner.optimizer import InfeasibleReason, InfeasibleRoute, PlanStation, plan_refuelling

D = Decimal


def station(opis_id, mile, price="3.00"):
    return PlanStation(opis_id, D(mile), D(price))


def infeasible(distance, stations=(), **kwargs):
    with pytest.raises(InfeasibleRoute) as caught:
        plan_refuelling(D(distance), list(stations), mpg=D(10), max_range_miles=D(500), **kwargs)
    return caught.value


def test_gap_between_stations():
    error = infeasible(800, [station(1, 100), station(2, 700)])
    assert error.reason == InfeasibleReason.STATION_GAP
    assert (error.gap_start_mile, error.gap_end_mile) == (100, 700)
    assert error.usable_range_miles == 500
    assert error.start_fuel_gallons is None
    assert error.gallons_short is None


def test_no_stations_on_a_long_route_is_a_gap_from_the_start_to_the_finish():
    error = infeasible(900)
    assert error.reason == InfeasibleReason.STATION_GAP
    assert (error.gap_start_mile, error.gap_end_mile) == (0, 900)


def test_start_fuel_short_of_the_first_station_reports_the_details():
    error = infeasible(300, [station(1, 150)], start_fuel_gallons=D(10))
    assert error.reason == InfeasibleReason.START_FUEL_INSUFFICIENT
    assert (error.gap_start_mile, error.gap_end_mile) == (100, 150)
    assert error.start_fuel_gallons == 10
    assert error.gallons_short == 5
    assert error.usable_range_miles == 500


def test_empty_tank_without_a_station_at_mile_zero():
    error = infeasible(300, [station(1, 50)], start_fuel_gallons=D(0))
    assert error.reason == InfeasibleReason.START_FUEL_INSUFFICIENT
    assert (error.gap_start_mile, error.gap_end_mile) == (0, 50)
    assert error.gallons_short == 5


def test_nothing_within_a_full_tank_of_the_start_is_a_gap_even_with_a_part_full_tank():
    error = infeasible(900, [station(1, 600)], start_fuel_gallons=D(10))
    assert error.reason == InfeasibleReason.STATION_GAP
    assert (error.gap_start_mile, error.gap_end_mile) == (0, 600)
    assert error.start_fuel_gallons is None


def test_messages_are_readable():
    gap = str(infeasible(800, [station(1, 100), station(2, 700)]))
    assert gap == "station gap: no fuel point between mile 100 and mile 700 (range 500 mi)"

    start = str(infeasible(300, [station(1, 150)], start_fuel_gallons=D(10)))
    assert start == (
        "start fuel insufficient: 10 gal covers 100 mi, next fuel point at mile 150 (5 gal short)"
    )
