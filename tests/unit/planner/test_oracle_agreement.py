"""T005, T008: on 50 seeded random small trips the optimizer matches the brute-force optimum."""

import random
from decimal import Decimal

import pytest

from planner.optimizer import InfeasibleRoute, PlanStation, plan_refuelling
from tests.unit.planner.oracle import oracle_cost, random_instance

SEEDS = range(50)


def solve(seed):
    distance, stations, capacity, start_fuel = random_instance(random.Random(seed))
    expected = oracle_cost(distance, stations, capacity, start_fuel)

    def run():
        return plan_refuelling(
            Decimal(distance),
            [PlanStation(i, Decimal(mile), Decimal(price)) for i, mile, price in stations],
            mpg=Decimal(1),
            max_range_miles=Decimal(capacity),
            start_fuel_gallons=Decimal(start_fuel),
        )

    return expected, run


@pytest.mark.parametrize("seed", SEEDS)
def test_cost_matches_the_oracle(seed):
    expected, run = solve(seed)
    if expected is None:
        pytest.skip("infeasible instance (see test_feasibility_matches_the_oracle)")
    assert run().total_cost_usd == Decimal(expected)


@pytest.mark.parametrize("seed", SEEDS)
def test_feasibility_matches_the_oracle(seed):
    expected, run = solve(seed)
    if expected is None:
        with pytest.raises(InfeasibleRoute):
            run()
    else:
        run()
