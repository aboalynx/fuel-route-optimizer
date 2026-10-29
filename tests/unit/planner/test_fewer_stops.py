"""T026: the minimum-saving-per-stop rule on top of the cheapest plan (pure, no Django)."""

import ast
import inspect
import random
from decimal import Decimal

import pytest

import planner.fewer_stops
from planner.fewer_stops import plan_with_min_saving
from planner.optimizer import (
    FuelPlan,
    FuelPurchase,
    InfeasibleRoute,
    PlanStation,
    plan_refuelling,
)
from tests.unit.planner.oracle import random_instance
from tests.unit.planner.test_oracle_agreement import COSTLY_SEEDS

D = Decimal
VEHICLE = {"mpg": D(10), "max_range_miles": D(500)}

# Cheapest plan: fill at A, top up 1 gal at B ($3.01), then C: $127.01. Dropping A costs $0.25
# more, dropping B $0.49, and C cannot be dropped (no other way to reach the finish).
SMALL_SAVINGS = [
    PlanStation(1, D(250), D("3.00")),
    PlanStation(2, D(260), D("3.01")),
    PlanStation(3, D(600), D("3.50")),
]


def station(opis_id, mile, price):
    return PlanStation(opis_id, D(mile), D(price))


def run(distance, stations, min_saving, **vehicle):
    return plan_with_min_saving(
        D(distance), stations, min_saving_usd=D(min_saving), **{**VEHICLE, **vehicle}
    )


def test_zero_returns_the_cheapest_plan_unchanged():
    for distance, stations in [
        (900, SMALL_SAVINGS),
        (900, [station(1, 300, "3.50"), station(2, 450, "3.00")]),
        (400, [station(1, 200, "3.00")]),
    ]:
        result = run(distance, stations, 0)
        cheapest = plan_refuelling(D(distance), stations, **VEHICLE)
        assert result.plan == result.cheapest == cheapest
        assert result.stops_dropped == 0
        assert result.extra_cost_vs_cheapest_usd == 0


def test_a_stop_that_saves_little_is_dropped():
    cheapest = plan_refuelling(D(900), SMALL_SAVINGS, **VEHICLE)
    assert [p.opis_id for p in cheapest.purchases] == [1, 2, 3]
    assert cheapest.total_cost_usd == D("127.01")

    result = run(900, SMALL_SAVINGS, 5)
    assert [p.opis_id for p in result.plan.purchases] == [2, 3]  # A saved only $0.25
    assert result.stops_dropped == 1
    assert result.extra_cost_vs_cheapest_usd == D("0.25")
    assert result.plan.gallons_purchased == cheapest.gallons_purchased


def test_threshold_below_every_saving_drops_nothing():
    result = run(900, SMALL_SAVINGS, "0.20")
    assert result.plan == result.cheapest
    assert result.stops_dropped == 0


def test_a_stop_the_trip_needs_is_never_dropped():
    result = run(700, [station(1, 300, "3.00")], 100)
    assert [p.opis_id for p in result.plan.purchases] == [1]
    assert result.stops_dropped == 0


def every_stop_saves_at_least(result, distance, stations, threshold, **vehicle):
    by_id = {s.opis_id: s for s in stations}
    kept = [by_id[p.opis_id] for p in result.plan.purchases]
    for purchase in result.plan.purchases:
        others = [s for s in kept if s.opis_id != purchase.opis_id]
        try:
            alt = plan_refuelling(distance, others, **vehicle)
        except InfeasibleRoute:
            continue
        assert alt.total_cost_usd - result.plan.total_cost_usd >= threshold


@pytest.mark.parametrize("threshold", ["0.5", "5", "50"])
@pytest.mark.parametrize("seed", COSTLY_SEEDS[:25])  # feasible trips that buy fuel
def test_every_kept_stop_saves_the_threshold_or_is_needed(seed, threshold):
    distance, rows, capacity, start = random_instance(random.Random(seed))
    stations = [PlanStation(i, D(m), D(p)) for i, m, p in rows]
    vehicle = {"mpg": D(1), "max_range_miles": D(capacity), "start_fuel_gallons": D(start)}
    result = plan_with_min_saving(D(distance), stations, min_saving_usd=D(threshold), **vehicle)
    every_stop_saves_at_least(result, D(distance), stations, D(threshold), **vehicle)
    assert result.extra_cost_vs_cheapest_usd >= 0
    assert result.stops_dropped == len(result.cheapest.purchases) - len(result.plan.purchases)


def fake_planner(costs):
    """A plan_refuelling stand-in: buys 1 gal at each given station; the total comes from
    `costs`, keyed by the set of station ids (missing key = infeasible)."""

    def plan(distance, stations, **vehicle):
        ids = frozenset(s.opis_id for s in stations)
        if ids not in costs:
            raise InfeasibleRoute("station gap", D(0), distance, D(500))
        purchases = tuple(
            FuelPurchase(s.opis_id, s.mile_marker, D(1), D(1), D(1)) for s in stations
        )
        return FuelPlan(purchases, D(1), D(len(purchases)), costs[ids], D(0))

    return plan


@pytest.mark.parametrize(("miles", "dropped_first"), [((100, 200), 1), ((150, 150), 1)])
def test_ties_go_to_the_earlier_mile_then_the_lower_id(monkeypatch, miles, dropped_first):
    # Dropping 1 or 2 costs the same $0.10; dropping both costs $1.00; 3 is always needed.
    costs = {
        frozenset({1, 2, 3}): D("100.00"),
        frozenset({1, 3}): D("100.10"),
        frozenset({2, 3}): D("100.10"),
        frozenset({3}): D("101.00"),
    }
    monkeypatch.setattr(planner.fewer_stops, "plan_refuelling", fake_planner(costs))
    stations = [station(1, miles[0], "3"), station(2, miles[1], "3"), station(3, 400, "3")]
    result = run(1000, stations, "0.50")
    kept = [p.opis_id for p in result.plan.purchases]
    assert dropped_first not in kept
    assert kept == [2, 3]


@pytest.mark.parametrize(("value", "error"), [("-1", ValueError), ("101", ValueError)])
def test_out_of_range_threshold(value, error):
    with pytest.raises(error, match="min_saving_usd"):
        run(900, SMALL_SAVINGS, value)


def test_float_threshold_is_a_type_error():
    with pytest.raises(TypeError):
        plan_with_min_saving(D(900), SMALL_SAVINGS, min_saving_usd=5.0, **VEHICLE)


def test_infeasible_cheapest_plan_propagates():
    with pytest.raises(InfeasibleRoute):
        run(900, [station(1, 100, "3")], 5)


def test_deterministic():
    assert run(900, SMALL_SAVINGS, 5) == run(900, SMALL_SAVINGS, 5)


def test_fewer_stops_module_does_not_import_django():
    tree = ast.parse(inspect.getsource(planner.fewer_stops))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)

    assert not any(name.split(".")[0] == "django" for name in modules)
