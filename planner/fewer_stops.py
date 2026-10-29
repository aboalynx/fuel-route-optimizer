"""Minimum saving per stop on top of the cheapest plan (pure, no Django).

See docs/algorithms/refuelling-greedy.md, "Fewer stops".
"""

from dataclasses import dataclass
from decimal import Decimal

from planner.optimizer import FuelPlan


@dataclass(frozen=True)
class FewerStopsResult:
    plan: FuelPlan  # the plan returned to the client
    cheapest: FuelPlan  # the 003 optimum
    stops_dropped: int

    @property
    def extra_cost_vs_cheapest_usd(self) -> Decimal:
        return self.plan.total_cost_usd - self.cheapest.total_cost_usd
