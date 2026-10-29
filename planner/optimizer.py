"""Cheapest refuelling plan along a fixed route (pure, stdlib decimal only).

The greedy from docs/algorithms/refuelling-greedy.md (ADR-0001). Every number is a Decimal; each
stop's cost is rounded half up to cents once, and the total is the sum of the rounded stop costs.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

CENT = Decimal("0.01")
INFINITY = Decimal("Infinity")
MAX_RESERVE_GALLONS = Decimal(25)


@dataclass(frozen=True)
class PlanStation:
    opis_id: int
    mile_marker: Decimal
    price_usd_per_gallon: Decimal  # exact


@dataclass(frozen=True)
class FuelPurchase:
    opis_id: int
    mile_marker: Decimal
    price_usd_per_gallon: Decimal
    gallons: Decimal
    cost_usd: Decimal  # rounded half up to cents


@dataclass(frozen=True)
class FuelPlan:
    purchases: tuple[FuelPurchase, ...]
    gallons_consumed: Decimal
    gallons_purchased: Decimal
    total_cost_usd: Decimal  # sum of the rounded stop costs
    fuel_left_gallons: Decimal


class InfeasibleReason(StrEnum):
    STATION_GAP = "station gap"
    START_FUEL_INSUFFICIENT = "start fuel insufficient"


class InfeasibleRoute(Exception):
    """The trip cannot be completed. For START_FUEL_INSUFFICIENT, gap_start_mile is how far the
    usable start fuel reaches and gap_end_mile is the next fuel point."""

    def __init__(
        self,
        reason: InfeasibleReason,
        gap_start_mile: Decimal,
        gap_end_mile: Decimal,
        usable_range_miles: Decimal,
        start_fuel_gallons: Decimal | None = None,
        gallons_short: Decimal | None = None,
    ):
        self.reason = reason
        self.gap_start_mile = gap_start_mile
        self.gap_end_mile = gap_end_mile
        self.usable_range_miles = usable_range_miles
        self.start_fuel_gallons = start_fuel_gallons
        self.gallons_short = gallons_short
        if reason == InfeasibleReason.START_FUEL_INSUFFICIENT:
            message = (
                f"{reason}: {_fmt(start_fuel_gallons)} gal covers {_fmt(gap_start_mile)} mi, "
                f"next fuel point at mile {_fmt(gap_end_mile)} ({_fmt(gallons_short)} gal short)"
            )
        else:
            message = (
                f"{reason}: no fuel point between mile {_fmt(gap_start_mile)} and mile "
                f"{_fmt(gap_end_mile)} (range {_fmt(usable_range_miles)} mi)"
            )
        super().__init__(message)


def round_cents(amount_usd: Decimal) -> Decimal:
    return amount_usd.quantize(CENT, rounding=ROUND_HALF_UP)


def plan_refuelling(
    distance_miles: Decimal,
    stations: Sequence[PlanStation],
    *,
    mpg: Decimal,
    max_range_miles: Decimal,
    start_fuel_gallons: Decimal | None = None,
    reserve_gallons: Decimal = Decimal(0),
) -> FuelPlan:
    """The cheapest plan, or InfeasibleRoute. Invalid input raises ValueError or TypeError."""
    capacity_gallons = _validate(
        distance_miles, stations, mpg, max_range_miles, start_fuel_gallons, reserve_gallons
    )
    if start_fuel_gallons is None:
        start_fuel_gallons = capacity_gallons

    # Fuel is held in miles of range, so every sum below is exact for any mpg (research R2).
    # The reserve is never touched: the same loop runs on the fuel above it (research R7).
    # The origin is priced +inf (nothing can be bought there), the destination 0 (buy only what
    # is needed to finish).
    nodes = (
        [_Node(Decimal(0), INFINITY, 0)]
        + [_Node(s.mile_marker, s.price_usd_per_gallon, s.opis_id) for s in stations]
        + [_Node(distance_miles, Decimal(0), 0)]
    )
    capacity = max_range_miles - reserve_gallons * mpg
    fuel = (start_fuel_gallons - reserve_gallons) * mpg
    purchases = []
    i = 0
    while i < len(nodes) - 1:
        here = nodes[i]
        j, cheaper = _next_node(nodes, i, capacity)
        if j is None:  # nothing within a full tank, whatever the start fuel
            raise InfeasibleRoute(
                InfeasibleReason.STATION_GAP, here.mile, nodes[i + 1].mile, capacity
            )
        leg = nodes[j].mile - here.mile
        buy = max(Decimal(0), leg - fuel) if cheaper else capacity - fuel
        if i == 0 and buy > 0:  # fuel cannot be bought at the start
            raise InfeasibleRoute(
                InfeasibleReason.START_FUEL_INSUFFICIENT,
                fuel,
                nodes[j].mile,
                capacity,
                start_fuel_gallons=start_fuel_gallons,
                gallons_short=buy / mpg,
            )
        if buy > 0:
            gallons = buy / mpg
            purchases.append(
                FuelPurchase(
                    opis_id=here.opis_id,
                    mile_marker=here.mile,
                    price_usd_per_gallon=here.price,
                    gallons=gallons,
                    cost_usd=round_cents(gallons * here.price),
                )
            )
        fuel += buy - leg
        i = j

    return FuelPlan(
        purchases=tuple(purchases),
        gallons_consumed=distance_miles / mpg,
        gallons_purchased=sum((p.gallons for p in purchases), Decimal(0)),
        total_cost_usd=sum((p.cost_usd for p in purchases), Decimal("0.00")),
        fuel_left_gallons=fuel / mpg + reserve_gallons,
    )


@dataclass(frozen=True)
class _Node:
    mile: Decimal
    price: Decimal
    opis_id: int  # 0 for the origin and destination


def _next_node(nodes: list[_Node], i: int, capacity: Decimal) -> tuple[int | None, bool]:
    """Where to go from node i: (the first strictly cheaper node in range, True), else
    (the cheapest node in range, farthest then lowest opis_id on ties, False), else (None, False).
    """
    here = nodes[i]
    best = None
    k = i + 1
    while k < len(nodes) and nodes[k].mile - here.mile <= capacity:
        node = nodes[k]
        if node.price < here.price:
            return k, True
        if best is None or (node.price, -node.mile, node.opis_id) < (
            nodes[best].price,
            -nodes[best].mile,
            nodes[best].opis_id,
        ):
            best = k
        k += 1
    return best, False


def _validate(
    distance_miles, stations, mpg, max_range_miles, start_fuel_gallons, reserve_gallons
) -> Decimal:
    """Check every input; return the tank capacity in gallons."""
    for name, value in [
        ("distance_miles", distance_miles),
        ("mpg", mpg),
        ("max_range_miles", max_range_miles),
    ]:
        _require_decimal(name, value)
    if distance_miles < 0:
        raise ValueError(f"distance_miles must be >= 0, got {distance_miles}")
    if mpg <= 0:
        raise ValueError(f"mpg must be > 0, got {mpg}")
    if max_range_miles <= 0:
        raise ValueError(f"max_range_miles must be > 0, got {max_range_miles}")

    capacity_gallons = max_range_miles / mpg
    if start_fuel_gallons is not None:
        _require_decimal("start_fuel_gallons", start_fuel_gallons)
        if not 0 <= start_fuel_gallons <= capacity_gallons:
            raise ValueError(
                f"start_fuel_gallons must be between 0 and {capacity_gallons}, "
                f"got {start_fuel_gallons}"
            )

    _require_decimal("reserve_gallons", reserve_gallons)
    if not 0 <= reserve_gallons <= MAX_RESERVE_GALLONS:
        raise ValueError(
            f"reserve_gallons must be between 0 and {MAX_RESERVE_GALLONS}, got {reserve_gallons}"
        )
    if reserve_gallons >= capacity_gallons:
        raise ValueError(
            f"reserve_gallons must be less than the tank capacity ({capacity_gallons} gal), "
            f"got {reserve_gallons}"
        )
    if start_fuel_gallons is not None and start_fuel_gallons < reserve_gallons:
        raise ValueError(
            f"start_fuel_gallons ({start_fuel_gallons}) must be at least reserve_gallons "
            f"({reserve_gallons})"
        )

    previous = None
    for station in stations:
        _require_decimal("mile_marker", station.mile_marker)
        _require_decimal("price_usd_per_gallon", station.price_usd_per_gallon)
        if not 0 <= station.mile_marker <= distance_miles:
            raise ValueError(
                f"station {station.opis_id}: mile_marker must be between 0 and "
                f"{distance_miles}, got {station.mile_marker}"
            )
        if station.price_usd_per_gallon <= 0:
            raise ValueError(
                f"station {station.opis_id}: price_usd_per_gallon must be > 0, "
                f"got {station.price_usd_per_gallon}"
            )
        key = (station.mile_marker, station.opis_id)
        if previous is not None and key <= previous:
            raise ValueError("stations must be sorted by (mile_marker, opis_id) order")
        previous = key
    return capacity_gallons


def _fmt(value: Decimal) -> str:
    """Plain digits without trailing zeros: Decimal("100.000") -> "100"."""
    return f"{value.normalize():f}"


def _require_decimal(name: str, value) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be a Decimal, got {type(value).__name__}")
