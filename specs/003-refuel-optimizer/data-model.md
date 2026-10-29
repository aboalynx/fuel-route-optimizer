# Data Model: Refuel Optimizer (003)

No database tables. Everything here is an in-memory value type in `planner/optimizer.py` (pure,
stdlib `decimal` only). Every number is a `Decimal`; units are in the names (constitution V).

## Inputs

### `PlanStation` (frozen dataclass)

| Field | Type | Rules |
| --- | --- | --- |
| `opis_id` | `int` | Station ID from Feature 001 |
| `mile_marker` | `Decimal` | 0 ≤ value ≤ `distance_miles`, quantized to 0.001 by the caller |
| `price_usd_per_gallon` | `Decimal` | > 0, exact (up to 8 dp) |

The sequence passed in must be sorted by `(mile_marker, opis_id)`, as Feature 002 returns it.

### `plan_refuelling` arguments

| Argument | Type | Rules | Default (set by the caller from settings) |
| --- | --- | --- | --- |
| `distance_miles` | `Decimal` | ≥ 0 | — |
| `stations` | `Sequence[PlanStation]` | sorted, in range | — |
| `mpg` | `Decimal` | > 0 | `VEHICLE_MPG` = 10 |
| `max_range_miles` | `Decimal` | > 0 | `VEHICLE_MAX_RANGE_MILES` = 500 |
| `start_fuel_gallons` | `Decimal` | reserve ≤ value ≤ capacity | capacity (full tank) |
| `reserve_gallons` | `Decimal` | 0 ≤ value ≤ 25, < capacity | 0 |

Derived: `capacity_gallons = max_range_miles / mpg` (50). Inside the loop fuel is held in miles of
range (research R2): usable capacity `max_range_miles − reserve·mpg`, usable start fuel
`(start_fuel − reserve)·mpg`.

Any rule broken → `ValueError` (a non-`Decimal` number → `TypeError`). Feature 004 maps both to 400.

## Outputs

### `FuelPurchase` (frozen dataclass)

| Field | Type | Rules |
| --- | --- | --- |
| `opis_id` | `int` | The station |
| `mile_marker` | `Decimal` | As given |
| `price_usd_per_gallon` | `Decimal` | Exact, as given |
| `gallons` | `Decimal` | > 0, exact |
| `cost_usd` | `Decimal` | `gallons × price` rounded half up to cents (research R3) |

### `FuelPlan` (frozen dataclass)

| Field | Type | Rules |
| --- | --- | --- |
| `purchases` | `tuple[FuelPurchase, ...]` | Route order; only stops where fuel is bought; may be empty |
| `gallons_consumed` | `Decimal` | `distance_miles / mpg` |
| `gallons_purchased` | `Decimal` | Sum of `purchases[].gallons` |
| `total_cost_usd` | `Decimal` | Sum of `purchases[].cost_usd` (cents) |
| `fuel_left_gallons` | `Decimal` | ≥ reserve; `start + purchased − left = consumed` exactly |

**Invariants (tested):**
- fuel balance holds exactly;
- the tank never exceeds capacity nor drops below the reserve at any node;
- no leg between consecutive fuel points (start, stops, finish) is longer than the usable range;
- the same input gives an equal `FuelPlan`.

### `InfeasibleReason` (`StrEnum`)

`STATION_GAP = "station gap"`, `START_FUEL_INSUFFICIENT = "start fuel insufficient"`.

### `InfeasibleRoute` (exception)

| Field | Type | Rules |
| --- | --- | --- |
| `reason` | `InfeasibleReason` | One per failure |
| `gap_start_mile` | `Decimal` | Station gap: the last reachable fuel point. Start fuel: the mile the usable start fuel covers |
| `gap_end_mile` | `Decimal` | The next fuel point (station or finish) |
| `usable_range_miles` | `Decimal` | `max_range_miles − reserve·mpg` |
| `start_fuel_gallons` | `Decimal \| None` | Only for `START_FUEL_INSUFFICIENT` |
| `gallons_short` | `Decimal \| None` | Only for `START_FUEL_INSUFFICIENT`: `(gap_end − gap_start) / mpg` |

`str()` is readable, e.g. `start fuel insufficient: 10 gal covers 100 mi, next fuel point at mile
150 (5 gal short)` and `station gap: no fuel point between mile 100 and mile 700 (range 500 mi)`.

## Flow

```text
validate inputs ──invalid──▶ ValueError / TypeError
      │
nodes = [origin(0, +∞)] + stations + [destination(D, 0)]
      │
i = origin ──▶ window empty? ──▶ InfeasibleRoute(STATION_GAP)
      │        at origin and buy > 0? ──▶ InfeasibleRoute(START_FUEL_INSUFFICIENT)
      │        record purchase (if buy > 0), move to j
      └── until i = destination ──▶ FuelPlan
```
