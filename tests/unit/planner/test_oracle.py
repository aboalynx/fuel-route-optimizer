"""T001: the brute-force test oracle checks itself on hand-worked cases."""

import random

from tests.unit.planner.oracle import oracle_cost, random_instance


def test_trip_within_start_fuel_costs_nothing():
    assert oracle_cost(8, [(1, 3, 5)], capacity=10, start_fuel=10) == 0


def test_one_needed_station_costs_exactly_the_shortfall():
    # 10 units reach mile 10; the last 5 miles need 5 units at $2.
    assert oracle_cost(15, [(1, 10, 2)], capacity=10, start_fuel=10) == 10


def test_cheaper_station_later_is_preferred():
    # Buy 2 at $9 to reach mile 4, then 6 at $1: 18 + 6 = 24.
    assert oracle_cost(10, [(1, 2, 9), (2, 4, 1)], capacity=10, start_fuel=2) == 24


def test_gap_longer_than_capacity_is_infeasible():
    assert oracle_cost(30, [(1, 5, 1), (2, 20, 1)], capacity=10, start_fuel=10) is None


def test_start_fuel_short_of_first_station_is_infeasible():
    assert oracle_cost(10, [(1, 6, 1)], capacity=10, start_fuel=5) is None


def test_empty_tank_with_station_at_mile_zero_is_feasible():
    assert oracle_cost(4, [(1, 0, 3)], capacity=10, start_fuel=0) == 12


def test_random_instances_respect_their_bounds():
    for seed in range(50):
        distance, stations, capacity, start_fuel = random_instance(random.Random(seed))
        assert 5 <= capacity <= 15
        assert 0 <= start_fuel <= capacity
        assert 0 <= len(stations) <= 8
        assert distance <= 40
        assert sorted(s[0] for s in stations) == list(range(1, len(stations) + 1))
        assert stations == sorted(stations, key=lambda s: (s[1], s[0]))
        assert all(0 <= mile <= distance and 1 <= price <= 9 for _, mile, price in stations)
