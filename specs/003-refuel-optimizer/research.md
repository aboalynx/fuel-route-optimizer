# Research: Refuel Optimizer (003)

All decisions below resolve the Technical Context. Nothing is left as NEEDS CLARIFICATION. The
algorithm itself is decided in [ADR-0001](../../docs/adr/0001-greedy-refuelling-optimizer.md) and
described in [refuelling-greedy.md](../../docs/algorithms/refuelling-greedy.md); this file records
the choices made on top of it.

## R1. Algorithm: greedy "next strictly cheaper node"

- **Decision:** the greedy from ADR-0001. Nodes sorted by `(mile, opis_id)` are origin (mile 0,
  price +∞), the stations, then destination (mile D, price 0). From node `i`, with window = the
  nodes `j > i` within the usable range:
  - a strictly cheaper node in the window → buy just enough to reach the **first** one;
  - otherwise → fill the tank and go to the cheapest node in the window, ties to the farthest,
    then the lowest `opis_id` (spec Clarifications Q2);
  - an empty window → `InfeasibleRoute(STATION_GAP, mile[i], mile[i+1])`.
- **Rationale:** optimal for this model (exchange argument in the algorithm doc), deterministic,
  `O(n·w)`, and exact with `Decimal`. The destination priced 0 makes the truck buy only what it
  needs to finish (spec US1 scenario 4); a regression test guards it.
- **Alternatives considered:** DP over fuel levels (kept as the test oracle, R6), LP (needs a
  solver and floats), "refuel below ¼ tank" heuristics (not optimal).

## R2. Internal fuel unit: miles of range, not gallons

- **Decision:** inside the loop, fuel is tracked in **miles of range** (`gallons × mpg`). Capacity
  is `max_range_miles`, start fuel is `start_fuel_gallons × mpg`, the reserve is
  `reserve_gallons × mpg`. A purchase of `x` miles is reported as `x / mpg` gallons.
- **Rationale:** mile markers are quantized to 0.001 (R5), so every distance, every purchase and
  the fuel balance are exact `Decimal` sums for **any** mpg. Dividing only once per reported value
  keeps gallons exact for the default 10 mpg (and any mpg that divides a power of ten). Tracking
  gallons inside would divide on every leg and could accumulate tiny remainders with an odd mpg.
- **Alternatives considered:** gallons inside (division on every leg); a high-precision decimal
  context (still not exact for 1/3, and hides the issue).

## R3. Money and rounding

- **Decision:** prices are exact `Decimal` (up to 8 dp, as stored by Feature 001) and are never
  rounded before multiplying. Each purchase's cost is `gallons × price`, computed exactly, then
  rounded once to cents with `ROUND_HALF_UP` when the `FuelPurchase` is built. The plan's
  `total_cost_usd` is the **sum of the rounded stop costs** (spec Clarifications Q3, FR-009).
  The rounding helper is `round_cents(x) = x.quantize(Decimal("0.01"), ROUND_HALF_UP)`.
- **Rationale:** the plan is the output boundary for money (constitution V): nothing downstream
  computes with these costs, it only displays them. Rounding in one pure place makes "stops add up
  to the total" testable here, to the cent (SC-003), instead of in the HTTP layer.
- **Alternatives considered:** round only in Feature 004's serializer (the total rule would then be
  untested in the core); round the exact total once (can differ by a cent from the stops shown);
  integer cents in the database (a price rounded to cents is off by up to 0.5¢/gal, up to 25¢ on
  a 50-gallon stop).

## R4. Infeasible versus invalid

- **Decision:** two different outcomes.
  - **Invalid input** → `ValueError` (or `TypeError` for a non-`Decimal` value) with a readable
    message. Feature 004 maps it to HTTP 400. Rules: `distance_miles ≥ 0`; `mpg > 0`;
    `max_range_miles > 0`; `0 ≤ reserve_gallons ≤ 25` and `reserve < capacity`;
    `reserve ≤ start_fuel_gallons ≤ capacity`; every station has `0 ≤ mile_marker ≤ distance`,
    `price > 0`; stations in `(mile_marker, opis_id)` order. All numbers must be `Decimal` (a
    float slipping in is a bug, so it fails loudly).
  - **Infeasible route** → `InfeasibleRoute` with an `InfeasibleReason` `StrEnum`:
    `STATION_GAP = "station gap"`, `START_FUEL_INSUFFICIENT = "start fuel insufficient"`.
    Feature 004 maps it to HTTP 422 with the details in the body.
- **Start fuel insufficient** is detected at the origin: if the first node the greedy heads for
  (the nearest station, or the finish) needs more than the usable start fuel, raise with
  `gap_start_mile` = miles the usable start fuel covers, `gap_end_mile` = that node's mile, and
  the details `start_fuel_gallons` and `gallons_short` (spec Clarifications Q1, FR-011). If no
  node is within the full usable range of the origin, it is a `STATION_GAP` from 0 instead (even a
  full tank would not help).
- **Price > 0:** a zero price would tie with the destination sentinel and make the "equal is not
  cheaper" rule buy fuel that is never used. Real prices are always positive, so 0 is invalid.
- **Alternatives considered:** returning an error value instead of raising (callers could forget to
  check); one exception for both (the API needs 400 vs 422).

## R5. Input shape and conversion from Feature 002

- **Decision:** the optimizer takes its own frozen dataclass `PlanStation(opis_id: int,
  mile_marker: Decimal, price_usd_per_gallon: Decimal)`. Feature 004's request service converts
  each 002 `Candidate` (float `mile_marker`, possibly `np.float64`) with
  `Decimal(float(m)).quantize(Decimal("0.001"))`, and the route distance the same way, clamping a
  marker that rounds above the distance down to it, then re-sorts by `(mile_marker, opis_id)`: two
  markers less than 0.0005 mi apart can otherwise quantize to the same mile in descending ID order
  and be rejected as unsorted.
- **Rationale:** the core stays independent of numpy floats and of the corridor module, and every
  number entering the money maths is an explicit `Decimal` (constitution V). 0.001 mi (~5 ft) is far
  below the corridor accuracy (0.05 mi).
- **Alternatives considered:** accept `Candidate` directly (drags floats into the money core);
  duck-typed objects (unclear contract).

## R6. Test oracle

- **Decision:** `tests/unit/planner/oracle.py`: a DP over (station, whole fuel units) on small
  integer instances: integer mile markers, integer prices, `mpg = 1` (one unit = one gallon = one
  mile), range 5–15, 0–8 stations, route length up to 40. About 50 cases from `random.Random(seed)`
  with fixed seeds. The cost check uses the first 50 seeds whose optimum is above $0 (seeds 0–122),
  so every case exercises the buying rules; the feasibility check uses seeds 0–49, a mix of
  feasible and infeasible trips. The test asserts that `plan.total_cost_usd` equals the oracle's cost (with
  integer prices and whole gallons every cost is a whole number of dollars, so cent rounding cannot
  hide a difference), and that both agree on feasibility.
- **Rationale:** with integer distances and mpg 1, an optimal plan exists that buys whole units at
  every stop (the greedy only ever buys differences of integer distances), so the integer DP finds
  the continuous optimum. Seeded cases keep the test deterministic (constitution I applies to the
  product; the test is also reproducible).
- **Alternatives considered:** hypothesis property tests (new dependency); brute force over every
  subset of stops (exponential, slower and less clear than the DP).

## R7. Reserve (optional extra)

- **Decision:** no separate code path. Validate `reserve ≤ start_fuel`, then run the same loop with
  usable capacity `C' = R − reserve·mpg` and usable start fuel `F0' = F0·mpg − reserve·mpg`. The
  reported fuel left adds the reserve back. A reserve of 0 is byte-for-byte the plain plan
  (spec US3 scenario 4).
- **Rationale:** the reserve is the first thing to drop if time is short; implementing it as a
  shift of two numbers keeps it a few lines and keeps the proof unchanged.

## R8. Performance

- **Decision:** a single forward pass. The window is scanned from `i+1` while the mile difference is
  ≤ range, stopping at the first strictly cheaper node; only the fill-up branch scans the whole
  window. No precomputation (sparse tables, heaps) is needed.
- **Rationale:** a coast-to-coast route has a few hundred candidates and a 500-mile window of at
  most ~150 of them, so the pass is well under 10 ms with `Decimal` (SC-006, measured by hand).
  Simplicity over cleverness (constitution VII).
