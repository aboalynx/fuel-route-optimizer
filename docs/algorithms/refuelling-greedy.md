# Algorithm: optimal refuelling along a route

Module `planner/optimizer.py` (pure, `decimal` only) · Feature 003 · [ADR-0001](../adr/0001-greedy-refuelling-optimizer.md)

## Context

A fixed route has length `D`. Stations sit at mile markers `m_i` with prices `p_i`.

- Range `R = VEHICLE_MAX_RANGE_MILES` (500).
- Tank capacity `C = R / VEHICLE_MPG` (50 gal).
- Start fuel `F0` (default `C`).
- Fuel is bought only at stations, in any fraction, never above `C`.

Find the cheapest plan, or the exact gap that makes the trip impossible.

## Decision

The nodes, sorted by `(mile, opis_id)`, are `origin (mile 0, price +∞)`, then the stations, then
`destination (mile D, price 0)`. The sentinel prices let one rule cover the start and the finish.

```text
i, fuel = origin, F0
while i != destination:
    window = nodes j > i with mile[j] - mile[i] <= R
    if not window: raise InfeasibleRoute("station_gap", mile[i], mile[i+1])
    j = first node in window with price[j] < price[i]           # strictly cheaper
    if j: buy = max(0, (mile[j] - mile[i]) / mpg - fuel)        # just enough to reach j
    else: buy = C - fuel; j = min(window, key=(price, -mile, opis_id))   # fill, go to cheapest
    if i is origin and buy > 0: raise InfeasibleRoute("start_fuel_insufficient", F0 * mpg, mile[j])
    record purchase if buy > 0
    fuel += buy - (mile[j] - mile[i]) / mpg; i = j
```

**Why it is optimal:**

- **Cheaper node ahead.** Any gallon bought at `i` beyond what reaches a strictly cheaper node `j` could be bought at `j` for less.
- **No cheaper node in range.** Every gallon used in the next `R` miles costs at least `p_i`, so a full tank is never worse.
- **Gap.** An empty window is a real gap; no plan can cross it.

**The destination fix.** Taken literally, the original work-plan pseudocode filled the tank when the
destination was in range but no cheaper *station* was. Pricing the destination at 0 makes the truck
buy only what it needs to finish.

**Optional reserve** (`reserve_gallons`, default 0, range 0–25; the first extra to drop if time is
short):

- Require `F0 ≥ reserve`.
- Run the same loop with `C' = C − reserve` and `F0' = F0 − reserve`, so the range is `C'·mpg`.
- With reserve 5, no leg exceeds 450 miles.

**Rules:**

- Ties: an equal price is not "cheaper"; among equally cheap stations, the farthest wins, then the lowest `opis_id`.
- Money: miles are quantized to `Decimal` 0.001 before the call, and every value inside is `Decimal`. Prices arrive unrounded (up to 8 dp).
- Rounding: only at the API boundary, ROUND_HALF_UP. The total is the sum of the rounded stop costs.
- Complexity: `O(n·w)` with `w` = stations within 500 mi, under 1 ms in practice.

## Rejected alternatives

DP over discretised fuel (same answer, more code; kept as the **test oracle**, ~50 seeded cases),
LP (needs a solver and floats), heuristics such as "refuel below ¼ tank" (not optimal).

## Consequences

- The result is optimal, deterministic and fully unit-testable. The proof fits in a short explanation.
- It is optimal only for the model: detour fuel, stop count and minimum purchases are ignored (README assumptions).
- A purely cost-optimal plan can include two stops close together for a small saving. A minimum-saving-per-stop rule is future work.
- Edge cases:
  - `D ≤ F0·mpg` → no stops.
  - `F0 = 0` → 422 unless a station is at mile 0.
  - No stations and `D > R` → `station_gap(0, D)`.
