"""T010: the optional safety reserve the tank never drops below (pure, no Django)."""

from decimal import Decimal

import pytest

from planner.optimizer import InfeasibleReason, InfeasibleRoute, PlanStation, plan_refuelling

D = Decimal
MPG = D(10)

STATIONS = [
    PlanStation(i, D(mile), D(price))
    for i, (mile, price) in enumerate(
        [
            (150, "3.40"),
            (380, "3.10"),
            (600, "3.55"),
            (790, "2.95"),
            (1150, "3.25"),
            (1400, "3.05"),
        ],
        start=1,
    )
]


def plan(distance, stations=STATIONS, **kwargs):
    return plan_refuelling(D(distance), stations, mpg=MPG, max_range_miles=D(500), **kwargs)


def test_reserve_shortens_every_leg_and_keeps_the_tank_above_it():
    result = plan(1700, reserve_gallons=D(5))

    fuel_points = [D(0)] + [p.mile_marker for p in result.purchases] + [D(1700)]
    assert all(b - a <= 450 for a, b in zip(fuel_points, fuel_points[1:], strict=False))

    fuel, position = D(50), D(0)
    for purchase in result.purchases:
        fuel -= (purchase.mile_marker - position) / MPG
        assert fuel >= 5
        fuel += purchase.gallons
        assert fuel <= 50
        position = purchase.mile_marker
    assert fuel - (D(1700) - position) / MPG == result.fuel_left_gallons
    assert result.fuel_left_gallons == 5
    assert D(50) + result.gallons_purchased - result.fuel_left_gallons == D(170)


def test_gap_that_fits_500_miles_but_not_450_is_infeasible_with_a_reserve():
    stations = [PlanStation(1, D(100), D(3)), PlanStation(2, D(570), D(3))]
    plan(900, stations)  # feasible without a reserve

    with pytest.raises(InfeasibleRoute) as caught:
        plan(900, stations, reserve_gallons=D(5))
    error = caught.value
    assert error.reason == InfeasibleReason.STATION_GAP
    assert (error.gap_start_mile, error.gap_end_mile) == (100, 570)
    assert error.usable_range_miles == 450


def test_start_fuel_short_of_the_first_station_counts_only_fuel_above_the_reserve():
    with pytest.raises(InfeasibleRoute) as caught:
        plan(300, [PlanStation(1, D(150), D(3))], start_fuel_gallons=D(15), reserve_gallons=D(5))
    error = caught.value
    assert error.reason == InfeasibleReason.START_FUEL_INSUFFICIENT
    assert (error.gap_start_mile, error.gap_end_mile) == (100, 150)
    assert error.start_fuel_gallons == 15
    assert error.reserve_gallons == 5
    assert error.gallons_short == 5
    assert str(error) == (
        "start fuel insufficient: 15 gal (5 gal kept as reserve) covers 100 mi, "
        "next fuel point at mile 150 (5 gal short)"
    )


def test_start_fuel_below_the_reserve_is_invalid_input():
    with pytest.raises(ValueError, match="reserve_gallons"):
        plan(300, start_fuel_gallons=D(4), reserve_gallons=D(5))


@pytest.mark.parametrize(
    ("reserve", "max_range"),
    [(D(-1), D(500)), (D(26), D(500)), (D(20), D(150)), (D(15), D(150))],
)
def test_reserve_out_of_range_is_invalid_input(reserve, max_range):
    with pytest.raises(ValueError, match="reserve_gallons"):
        plan_refuelling(
            D(100),
            [],
            mpg=MPG,
            max_range_miles=max_range,
            start_fuel_gallons=D(0) + max_range / MPG,
            reserve_gallons=reserve,
        )


def test_float_reserve_is_a_type_error():
    with pytest.raises(TypeError):
        plan(300, reserve_gallons=5.0)


@pytest.mark.parametrize("distance", [400, 900, 1700])
def test_zero_reserve_gives_the_plain_plan(distance):
    stations = [s for s in STATIONS if s.mile_marker <= distance]
    assert plan(distance, stations, reserve_gallons=D(0)) == plan(distance, stations)
