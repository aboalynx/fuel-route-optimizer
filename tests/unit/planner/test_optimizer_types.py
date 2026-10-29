"""T002: optimizer value types, cent rounding and input validation (pure, no Django)."""

import ast
import dataclasses
import inspect
import sys
from decimal import Decimal

import pytest

import planner.optimizer
from planner.optimizer import (
    FuelPlan,
    FuelPurchase,
    InfeasibleReason,
    PlanStation,
    plan_refuelling,
    round_cents,
)

D = Decimal
VEHICLE = {"mpg": D(10), "max_range_miles": D(500)}


def plan(distance, stations=(), **overrides):
    return plan_refuelling(D(distance), list(stations), **{**VEHICLE, **overrides})


def test_value_types_are_frozen_dataclasses_with_the_documented_fields():
    expected = {
        PlanStation: ["opis_id", "mile_marker", "price_usd_per_gallon"],
        FuelPurchase: ["opis_id", "mile_marker", "price_usd_per_gallon", "gallons", "cost_usd"],
        FuelPlan: [
            "purchases",
            "gallons_consumed",
            "gallons_purchased",
            "total_cost_usd",
            "fuel_left_gallons",
        ],
    }
    for cls, fields in expected.items():
        assert dataclasses.is_dataclass(cls)
        assert cls.__dataclass_params__.frozen
        assert [f.name for f in dataclasses.fields(cls)] == fields


def test_infeasible_reason_values():
    assert [r.value for r in InfeasibleReason] == ["station gap", "start fuel insufficient"]
    assert InfeasibleReason.STATION_GAP == "station gap"
    assert InfeasibleReason.START_FUEL_INSUFFICIENT == "start fuel insufficient"


@pytest.mark.parametrize(
    ("amount", "cents"),
    [("1.005", "1.01"), ("1.004999", "1.00"), ("2.675", "2.68"), ("3", "3.00")],
)
def test_round_cents_rounds_half_up(amount, cents):
    result = round_cents(D(amount))
    assert result == D(cents)
    assert result.as_tuple().exponent == -2


@pytest.mark.parametrize(
    ("kwargs", "field"),
    [
        ({"distance": -1}, "distance_miles"),
        ({"mpg": D(0)}, "mpg"),
        ({"mpg": D(-10)}, "mpg"),
        ({"max_range_miles": D(0)}, "max_range_miles"),
        ({"start_fuel_gallons": D(-1)}, "start_fuel_gallons"),
        ({"start_fuel_gallons": D("50.001")}, "start_fuel_gallons"),
        ({"stations": [PlanStation(1, D(-1), D(3))]}, "mile_marker"),
        ({"stations": [PlanStation(1, D(101), D(3))]}, "mile_marker"),
        ({"stations": [PlanStation(1, D(50), D(0))]}, "price_usd_per_gallon"),
        ({"stations": [PlanStation(1, D(50), D(-3))]}, "price_usd_per_gallon"),
        (
            {"stations": [PlanStation(1, D(60), D(3)), PlanStation(2, D(50), D(3))]},
            "order",
        ),
        (
            {"stations": [PlanStation(2, D(50), D(3)), PlanStation(1, D(50), D(3))]},
            "order",
        ),
    ],
)
def test_invalid_input_raises_value_error_naming_the_field(kwargs, field):
    distance = kwargs.pop("distance", 100)
    stations = kwargs.pop("stations", ())
    with pytest.raises(ValueError, match=field):
        plan(distance, stations, **kwargs)


@pytest.mark.parametrize(
    "call",
    [
        lambda: plan_refuelling(100.0, [], **VEHICLE),
        lambda: plan_refuelling(D(100), [], mpg=10.0, max_range_miles=D(500)),
        lambda: plan_refuelling(D(100), [], mpg=D(10), max_range_miles=500.0),
        lambda: plan(100, start_fuel_gallons=20.0),
        lambda: plan(100, [PlanStation(1, 50.0, D(3))]),
        lambda: plan(100, [PlanStation(1, D(50), 3.0)]),
    ],
)
def test_floats_raise_type_error(call):
    with pytest.raises(TypeError):
        call()


def test_optimizer_imports_only_the_standard_library():
    tree = ast.parse(inspect.getsource(planner.optimizer))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)

    assert all(name.split(".")[0] in sys.stdlib_module_names for name in modules)
