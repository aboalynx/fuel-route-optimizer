"""T004: the cheapest refuelling plan on hand-worked trips (pure, no Django).

Vehicle: 10 mpg, 500-mile range, so a 50-gallon tank, unless a test says otherwise.
"""

from decimal import Decimal

import pytest

from planner.optimizer import PlanStation, plan_refuelling, round_cents

D = Decimal
MPG = D(10)
RANGE = D(500)
CAPACITY = RANGE / MPG


def station(opis_id, mile, price):
    return PlanStation(opis_id, D(mile), D(price))


def plan(distance, stations=(), **kwargs):
    result = plan_refuelling(D(distance), list(stations), mpg=MPG, max_range_miles=RANGE, **kwargs)
    check_invariants(result, D(distance), kwargs.get("start_fuel_gallons", CAPACITY))
    return result


def check_invariants(result, distance, start):
    """Fuel balance, tank bounds and leg lengths hold on every feasible plan."""
    assert result.gallons_consumed == distance / MPG
    assert start + result.gallons_purchased - result.fuel_left_gallons == result.gallons_consumed
    assert result.gallons_purchased == sum((p.gallons for p in result.purchases), D(0))
    assert result.total_cost_usd == sum((p.cost_usd for p in result.purchases), D(0))

    fuel, position = start, D(0)
    for purchase in result.purchases:
        assert purchase.gallons > 0
        assert purchase.mile_marker >= position  # route order
        assert purchase.mile_marker - position <= RANGE
        fuel -= (purchase.mile_marker - position) / MPG
        assert fuel >= 0
        fuel += purchase.gallons
        assert fuel <= CAPACITY
        position = purchase.mile_marker
    assert distance - position <= RANGE
    assert fuel - (distance - position) / MPG == result.fuel_left_gallons
    assert result.fuel_left_gallons >= 0


def bought(result):
    return [(p.opis_id, p.gallons, p.cost_usd) for p in result.purchases]


@pytest.mark.parametrize(("distance", "left"), [(400, 10), (500, 0), (0, 50)])
def test_trip_within_range_on_a_full_tank_has_no_stops(distance, left):
    stations = [station(1, 200, "3.00")] if distance >= 200 else []
    result = plan(distance, stations)
    assert result.purchases == ()
    assert result.total_cost_usd == D("0.00")
    assert result.fuel_left_gallons == left


def test_passes_a_pricier_station_when_a_cheaper_one_is_in_range():
    result = plan(900, [station(1, 300, "3.50"), station(2, 450, "3.00")])
    assert bought(result) == [(2, D(40), D("120.00"))]
    assert result.fuel_left_gallons == 0


def test_buys_only_enough_to_reach_a_cheaper_station():
    # 10 gal reach A (mile 50) with 5 left; B is cheaper and 200 mi on, so buy 15 at A.
    stations = [station(1, 50, "4.00"), station(2, 250, "3.00")]
    result = plan(600, stations, start_fuel_gallons=D(10))
    assert bought(result) == [(1, D(15), D("60.00")), (2, D(35), D("105.00"))]
    assert result.total_cost_usd == D("165.00")


def test_fills_up_when_nothing_cheaper_is_in_range_and_goes_to_the_cheapest():
    # At A ($3.00) nothing in range is cheaper: fill to 50 gal, then go to C ($3.20), not B.
    stations = [station(1, 100, "3.00"), station(2, 400, "3.50"), station(3, 550, "3.20")]
    result = plan(1000, stations)
    assert bought(result) == [(1, D(10), D("30.00")), (3, D(40), D("128.00"))]


def test_buys_only_enough_to_finish_not_a_full_tank():
    # Destination-sentinel regression: at A the finish is in range, so buy 20 gal, not 30.
    result = plan(700, [station(1, 300, "3.00")])
    assert bought(result) == [(1, D(20), D("60.00"))]
    assert result.fuel_left_gallons == 0


def test_tie_goes_to_the_farthest_equally_cheap_station():
    stations = [station(1, 100, "3.00"), station(2, 200, "3.20"), station(3, 300, "3.20")]
    result = plan(800, stations)
    assert [p.opis_id for p in result.purchases] == [1, 3]
    assert result.total_cost_usd == D("94.00")


def test_tie_at_the_same_mile_goes_to_the_lower_station_id():
    stations = [station(1, 100, "3.00"), station(2, 300, "3.20"), station(3, 300, "3.20")]
    result = plan(800, stations)
    assert [p.opis_id for p in result.purchases] == [1, 2]


def test_cost_is_exact_and_rounded_half_up_per_stop():
    result = plan(900, [station(1, 300, "3.50"), station(2, 450, "3.00733333")])
    (purchase,) = result.purchases
    assert purchase.gallons == 40
    assert purchase.cost_usd == round_cents(D(40) * D("3.00733333")) == D("120.29")


def test_total_is_the_sum_of_rounded_stop_costs():
    # 0.5 gal x $2.03 = 1.015 -> 1.02 and 0.5 gal x $2.01 = 1.005 -> 1.01. The exact total 2.020
    # would round to 2.02; the plan reports 2.03 so the stops add up to the total shown.
    stations = [station(1, 0, "2.03"), station(2, 5, "2.01")]
    result = plan(10, stations, start_fuel_gallons=D(0))
    assert bought(result) == [(1, D("0.5"), D("1.02")), (2, D("0.5"), D("1.01"))]
    assert result.total_cost_usd == D("2.03")


def test_empty_tank_with_a_station_at_mile_zero_buys_there_first():
    result = plan(300, [station(1, 0, "3.00")], start_fuel_gallons=D(0))
    assert bought(result) == [(1, D(30), D("90.00"))]


def test_omitted_start_fuel_means_a_full_tank():
    stations = [station(1, 300, "3.50"), station(2, 450, "3.00")]
    assert plan(900, stations) == plan(900, stations, start_fuel_gallons=D(50))


def test_station_at_the_finish_mile_gets_no_purchase():
    result = plan(700, [station(1, 300, "3.00"), station(2, 700, "1.00")])
    assert bought(result) == [(1, D(20), D("60.00"))]
    assert result.fuel_left_gallons == 0


def test_same_input_gives_the_same_plan():
    stations = [station(i, 90 * i, f"3.{(7 * i) % 10}0") for i in range(1, 12)]
    assert plan(1100, stations) == plan(1100, stations)
