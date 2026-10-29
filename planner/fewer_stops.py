"""Minimum saving per stop on top of the cheapest plan (pure, no Django).

See docs/algorithms/refuelling-greedy.md, "Fewer stops".
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from planner.optimizer import FuelPlan, InfeasibleRoute, PlanStation, plan_refuelling


@dataclass(frozen=True)
class FewerStopsResult:
    plan: FuelPlan  # the plan returned to the client
    cheapest: FuelPlan  # the 003 optimum
    stops_dropped: int

    @property
    def extra_cost_vs_cheapest_usd(self) -> Decimal:
        return self.plan.total_cost_usd - self.cheapest.total_cost_usd


MAX_MIN_SAVING_USD = Decimal(100)


def plan_with_min_saving(
    distance_miles: Decimal,
    stations: Sequence[PlanStation],
    *,
    min_saving_usd: Decimal,
    **vehicle,
) -> FewerStopsResult:
    """The cheapest plan, then drop stops that save less than min_saving_usd.

    Each round re-plans over the current plan's stops minus one, for every stop, and drops the
    one whose removal costs least (ties: earlier mile, then lower opis_id) if that is below the
    threshold and the trip stays possible. Only the plan's own stops are considered: bringing
    other stations back in lets near-identical neighbours replace each other and cascade.
    With 0 the cheapest plan is returned unchanged. Raises InfeasibleRoute like plan_refuelling.
    """
    if not isinstance(min_saving_usd, Decimal):
        raise TypeError(f"min_saving_usd must be a Decimal, got {type(min_saving_usd).__name__}")
    if not 0 <= min_saving_usd <= MAX_MIN_SAVING_USD:
        raise ValueError(
            f"min_saving_usd must be between 0 and {MAX_MIN_SAVING_USD}, got {min_saving_usd}"
        )

    cheapest = plan_refuelling(distance_miles, stations, **vehicle)
    plan = cheapest
    if min_saving_usd > 0:
        by_id = {s.opis_id: s for s in stations}
        while (dropped := _cheapest_drop(plan, by_id, distance_miles, vehicle)) is not None:
            saving, alternative = dropped
            if saving >= min_saving_usd:
                break
            plan = alternative
    return FewerStopsResult(
        plan=plan,
        cheapest=cheapest,
        stops_dropped=len(cheapest.purchases) - len(plan.purchases),
    )


def _cheapest_drop(plan: FuelPlan, by_id, distance_miles, vehicle):
    """(saving, plan without that stop) for the stop that is cheapest to drop, or None."""
    kept = [by_id[p.opis_id] for p in plan.purchases]
    best = None
    for purchase in plan.purchases:
        others = [s for s in kept if s.opis_id != purchase.opis_id]
        try:
            alternative = plan_refuelling(distance_miles, others, **vehicle)
        except InfeasibleRoute:
            continue  # the trip needs this stop
        key = (
            alternative.total_cost_usd - plan.total_cost_usd,
            purchase.mile_marker,
            purchase.opis_id,
        )
        if best is None or key < best[0]:
            best = (key, alternative)
    return None if best is None else (best[0][0], best[1])
