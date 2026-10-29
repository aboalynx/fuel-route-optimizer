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
- Money: miles are quantized to `Decimal` 0.001 before the call, and every value inside is `Decimal`. Prices arrive unrounded (up to 8 dp). Inside the loop, fuel is held in miles of range (`gallons × mpg`), so every sum is exact for any mpg; gallons are computed only for the reported values.
- Rounding: happens once, when the plan is built (the money output), ROUND_HALF_UP to cents per stop. The total is the sum of the rounded stop costs. The API only formats.
- Infeasible details: `InfeasibleRoute` carries the reason (`station gap` or `start fuel insufficient`), the gap start and end miles and the usable range; for start fuel it also carries the start fuel and the gallons short.
- Complexity: `O(n·w)` with `w` = stations within 500 mi. Measured: 0.8 ms on the 202 real Dallas → Chicago candidates, 1.2 ms on 400 stations over 3,000 miles (2018 MacBook Pro).

## Fewer stops (optional, Feature 004)

`planner/fewer_stops.py` · request field `min_saving_per_stop_usd` (0–100, default 0 = off).

The greedy minimises fuel cost only, so it can stop for 1.3 gallons to save 10 cents. With a
threshold `X > 0`:

```text
plan = cheapest = plan_refuelling(all stations)
repeat:
    for each stop s of plan:
        alt_s = plan_refuelling(stops of plan without s)      # skip s if infeasible: it is needed
    s* = argmin (alt_s.total - plan.total, mile, opis_id)     # cheapest stop to drop
    if no s* or saving(s*) >= X: stop
    plan = alt_s*
```

- **Only the plan's own stops.** The first prototype re-planned over *all* candidates minus the
  dropped station. On Dallas → Chicago that cascaded: near-identical neighbours replaced each
  other one after another, and at X = $5 it removed 190 stations for +$34.98. Restricting the
  search to the current stops removes a real stop each round: +$0.17 for 2 fewer stops, 1.2 ms.
- **Guarantee:** every remaining stop either saves at least `X` (re-planning without it over the
  other stops costs at least `X` more) or cannot be removed. `X = 0` returns the 003 optimum, which
  the oracle checks.
- **Limit:** fewer stops, not always the fewest. A plan with fewer stops using other stations can
  exist; finding it exactly needs a search over stations and fuel levels (future work).
- **Measured:** Dallas → Chicago 4 → 2 stops (+$0.17); New York → Los Angeles 16 → 6 stops
  (+$7.12), with X = $5.

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
