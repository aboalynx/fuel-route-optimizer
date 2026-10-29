# Contract: refuel optimizer interface used by Feature 004

An in-process Python interface. There is no HTTP surface in this feature. Types are in
[data-model.md](../data-model.md).

```python
# planner/optimizer.py (pure; stdlib decimal only)
def plan_refuelling(
    distance_miles: Decimal,
    stations: Sequence[PlanStation],  # sorted by (mile_marker, opis_id)
    *,
    mpg: Decimal,
    max_range_miles: Decimal,
    start_fuel_gallons: Decimal | None = None,  # None -> full tank
    reserve_gallons: Decimal = Decimal(0),  # optional extra, 0..25
) -> FuelPlan: ...


def round_cents(amount_usd: Decimal) -> Decimal: ...  # quantize 0.01, ROUND_HALF_UP
```

**Guarantees:**

- **Optimal:** the lowest total cost for the model (fractional purchases at stations only, tank ≤
  capacity, never below the reserve); agrees with the DP oracle on every seeded case.
- **Buying rules:** a strictly cheaper node in range → buy just enough to reach the first one;
  otherwise fill and go to the cheapest in range (farthest, then lowest `opis_id`); the finish
  counts as a node priced 0, so the truck buys only what it needs to finish.
- **Exact:** no float anywhere; costs rounded half up to cents per stop, total = sum of rounded
  stop costs; fuel balance exact.
- **Deterministic and pure:** no I/O, no settings, no randomness.

**Errors:**

| Error | When | Feature 004 maps to |
| --- | --- | --- |
| `ValueError` / `TypeError` | Input cannot describe a real trip (data-model rules) | HTTP 400 `invalid_input` |
| `InfeasibleRoute(STATION_GAP, …)` | A stretch between fuel points is longer than the usable range | HTTP 422 `route_infeasible`, body has `reason`, `gap_start_mile`, `gap_end_mile`, `usable_range_miles` |
| `InfeasibleRoute(START_FUEL_INSUFFICIENT, …)` | The usable start fuel cannot reach the first fuel point | HTTP 422 `route_infeasible`, body also has `start_fuel_gallons`, `gallons_short`, `reserve_gallons` |

**Caller duties (Feature 004 request service):**

- read `Decimal(str(settings.VEHICLE_MPG))` and `Decimal(str(settings.VEHICLE_MAX_RANGE_MILES))`;
- convert each 002 `Candidate` to `PlanStation`, quantizing `mile_marker` and the route distance to
  0.001 mi and clamping a marker above the distance down to it, then **re-sorting by
  `(mile_marker, opis_id)`**: two float markers less than 0.0005 mi apart can quantize to the same
  mile in the wrong ID order, and the optimizer rejects unsorted input as invalid (research R5);
- pass the request's `start_fuel_gallons` (or `None`) and `reserve_gallons` (or 0).
