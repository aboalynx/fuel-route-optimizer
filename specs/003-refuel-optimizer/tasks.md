---

description: "Task list for Feature 003: Refuel Optimizer"
---

# Tasks: Refuel Optimizer

**Input**: Design documents from `specs/003-refuel-optimizer/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/refuel_optimizer.md, quickstart.md

**Tests**: Required (constitution IV: test-first, offline).

- Each test file is written first and run to show it failing (import or assertion errors) before its code exists. That output is the test-first record.
- No test touches Django, the database or the network. Every test file under `tests/unit/planner/` for this feature is pure.

**Organization**: US1 is the cheapest plan, US2 is the infeasible result with its details, US3 is the optional reserve. The value types, `round_cents` and input validation are foundational, because every story uses them.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on unfinished tasks)
- **[Story]**: US1 / US2 / US3 from spec.md
- Paths are repo-relative; `planner/` is a plain package (not a Django app)

---

## Phase 1: Setup

- [X] T001 Write the test oracle `tests/unit/planner/oracle.py` (research R6) and its own sanity tests in `tests/unit/planner/test_oracle.py`:
  - `oracle_cost(distance: int, stations: list[tuple[int, int, int]], capacity: int, start_fuel: int) -> int | None` where each station is `(opis_id, mile, price)`, `mpg = 1` (one unit = one gallon = one mile). It returns the minimum total cost, or `None` when no plan exists;
  - a DP over (node index, whole fuel units on arrival), buying whole units only at stations, never above `capacity`, never below 0;
  - `random_instance(rng: random.Random) -> (distance, stations, capacity, start_fuel)` with range 5–15, 0–8 stations, distance ≤ 40, integer prices 1–9, start fuel `0..capacity`, unique station IDs `1..n`, stations sorted by `(mile, opis_id)`, and `0 ≤ mile ≤ distance`;
  - sanity tests (hand-checked): a trip within the start fuel → 0; one station needed → the exact cost; a gap longer than `capacity` → `None`; start fuel 0 with a station at mile 0 → feasible.

---

## Phase 2: Foundational (blocking)

**Purpose**: the value types, the rounding helper and input validation (data-model.md, research R3–R5), used by all three stories.

- [X] T002 Write the failing test `tests/unit/planner/test_optimizer_types.py` (pure), covering:
  - `PlanStation`, `FuelPurchase`, `FuelPlan` are frozen dataclasses with exactly the fields in data-model.md;
  - `InfeasibleReason` values are exactly `STATION_GAP = "station gap"` and `START_FUEL_INSUFFICIENT = "start fuel insufficient"`;
  - `round_cents`: `Decimal("1.005") → Decimal("1.01")`, `Decimal("1.004999") → Decimal("1.00")`, `Decimal("2.675") → Decimal("2.68")` (half up, not banker's), result exponent is `-2`;
  - **validation** of `plan_refuelling` (each case → `ValueError` with a message naming the field): `distance_miles < 0`; `mpg <= 0`; `max_range_miles <= 0`; `start_fuel_gallons < 0` or `> capacity` (`capacity = max_range_miles / mpg`); a station with `mile_marker < 0` or `> distance_miles`; a station with `price_usd_per_gallon <= 0`; stations not sorted by `(mile_marker, opis_id)`;
  - a `float` for `distance_miles`, `mpg`, `max_range_miles`, `start_fuel_gallons`, a station's `mile_marker` or its price → `TypeError`;
  - `planner/optimizer.py` imports nothing outside the standard library and no Django (AST check, like `tests/unit/stations/test_enums.py`).
- [X] T003 Implement in `planner/optimizer.py`: `PlanStation(opis_id: int, mile_marker: Decimal, price_usd_per_gallon: Decimal)`, `FuelPurchase(opis_id, mile_marker, price_usd_per_gallon, gallons, cost_usd)`, `FuelPlan(purchases: tuple[FuelPurchase, ...], gallons_consumed, gallons_purchased, total_cost_usd, fuel_left_gallons)`, `InfeasibleReason` (`StrEnum`), `InfeasibleRoute(Exception)` with the fields in data-model.md, `round_cents(amount_usd) = amount_usd.quantize(Decimal("0.01"), ROUND_HALF_UP)`, and the `plan_refuelling(distance_miles, stations, *, mpg, max_range_miles, start_fuel_gallons=None, reserve_gallons=Decimal(0))` signature with the validation only (the body after validation may raise `NotImplementedError` for now). `None` start fuel means a full tank. Run T002 green.

**Checkpoint**: types and validation exist; the stories can start.

---

## Phase 3: User Story 1 - Get the cheapest fuel plan for a trip (Priority: P1) 🎯 MVP

**Goal**: `plan_refuelling()` returns the lowest-cost `FuelPlan` for any feasible trip, with exact money and fuel balance.

**Independent Test**: `tests/unit/planner/test_optimizer.py` (US1 cases) and `tests/unit/planner/test_oracle_agreement.py` pass, with no Django, DB or network (SC-001, SC-002, SC-003, SC-005).

### Tests for User Story 1 ⚠️ (write first, show failing)

- [X] T004 [P] [US1] Write `tests/unit/planner/test_optimizer.py` (pure). Use `mpg=Decimal(10)`, `max_range_miles=Decimal(500)` unless stated. Cases:
  - **No stops:** 400 mi, full tank → `purchases == ()`, `total_cost_usd == Decimal("0.00")`, `fuel_left_gallons == 10`; exactly 500 mi → no stops, 0 left; 0 mi → no stops.
  - **Pass a pricier station:** stations `(1, 300, 3.50)`, `(2, 450, 3.00)`, 900 mi (quickstart §2) → one purchase at station 2, `gallons == 40`, `cost_usd == Decimal("120.00")`, `fuel_left_gallons == 0`.
  - **Buy only enough to reach a cheaper station:** at a station with a strictly cheaper one in range, the purchase equals exactly the shortfall to reach it (hand-worked numbers in the test).
  - **Fill up when nothing is cheaper in range:** the purchase brings the tank to exactly 50 gal, and the next stop is the cheapest in range.
  - **Buy only enough to finish** (destination-sentinel regression): the finish is in range and no cheaper station precedes it → the last purchase leaves exactly 0 gal at the finish, never a full tank.
  - **Tie rule:** two equally cheapest stations at miles 200 and 300 → the plan goes to 300; two equally cheapest at the same mile → the lower `opis_id`; an equal price is never treated as cheaper.
  - **Exact money:** a price of `Decimal("3.00733333")` → `cost_usd == round_cents(gallons × price)`; `total_cost_usd == sum(p.cost_usd for p in purchases)` on a multi-stop plan where rounding each stop differs from rounding the exact total.
  - **Invariants** on every feasible case in this file: `start + gallons_purchased − fuel_left == gallons_consumed` exactly; `gallons_consumed == distance / mpg`; tank never above 50 or below 0 at any node; no leg between consecutive fuel points (start, stops, finish) longer than 500 mi; purchases in route order with `gallons > 0`.
  - **Start fuel 0** with a station at mile 0 → feasible, first purchase at mile 0.
  - **Default start fuel:** omitting `start_fuel_gallons` gives a plan equal to passing `Decimal(50)`.
  - **Station at the finish mile:** a cheap station exactly at mile D gets no purchase, and the truck arrives with 0 gal.
  - **Determinism:** two calls with the same input return equal `FuelPlan`s.
- [X] T005 [P] [US1] Write `tests/unit/planner/test_oracle_agreement.py` (pure): for seeds `0..49`, build `random_instance(random.Random(seed))`; when `oracle_cost` is not `None`, call `plan_refuelling` with `mpg=Decimal(1)`, `max_range_miles=Decimal(capacity)`, `start_fuel_gallons=Decimal(start_fuel)` and integer `Decimal` miles and prices, and assert `plan.total_cost_usd == Decimal(oracle_cost)`. Parametrize by seed so a failure names it.

### Implementation for User Story 1

- [X] T006 [US1] Implement the greedy in `plan_refuelling` (`planner/optimizer.py`), per research R1–R3 and `docs/algorithms/refuelling-greedy.md`:
  - nodes = origin `(mile 0, price +∞)`, the stations in order, destination `(mile D, price 0)`;
  - fuel held in **miles of range** (R2): capacity `max_range_miles`, start `start_fuel_gallons × mpg`;
  - from node `i`, window = nodes `j > i` with `mile[j] − mile[i] ≤ capacity`; scan stops at the first strictly cheaper node (R8);
  - strictly cheaper node found → buy `max(0, (mile[j] − mile[i]) − fuel)`; otherwise buy `capacity − fuel` and go to `min(window, key=(price, −mile, opis_id))`;
  - an empty window → `InfeasibleRoute(InfeasibleReason.STATION_GAP, ...)` with `gap_start_mile = mile[i]`, `gap_end_mile = mile[i+1]`; at the origin a positive buy → `InfeasibleRoute(InfeasibleReason.START_FUEL_INSUFFICIENT, ...)` with `gap_start_mile` = miles the start fuel covers, `gap_end_mile = mile[j]` (US2 fills in the remaining detail fields);
  - each purchase: `gallons = miles / mpg`, `cost_usd = round_cents(gallons × price)`; `total_cost_usd` = sum of rounded costs; `fuel_left_gallons` = remaining miles / mpg.

  Run T004 and T005 green; fix until the oracle agrees on every seed.

**Checkpoint**: US1 is complete; the cheapest plan is proven against the oracle.

---

## Phase 4: User Story 2 - Learn exactly where a trip is impossible (Priority: P2)

**Goal**: every impossible trip raises `InfeasibleRoute` with the right reason, gap miles and details, and never a plan (FR-010, FR-011, SC-004).

**Independent Test**: the US2 cases in `tests/unit/planner/test_infeasible.py` pass, and the oracle agrees on feasibility for every seed.

### Tests for User Story 2 ⚠️ (write first, show failing)

- [X] T007 [P] [US2] Write `tests/unit/planner/test_infeasible.py` (pure), covering:
  - stations at miles 100 and 700, 800 mi → `STATION_GAP`, `gap_start_mile == 100`, `gap_end_mile == 700`, `usable_range_miles == 500`, `start_fuel_gallons is None`, `gallons_short is None`;
  - no stations, 900 mi → `STATION_GAP` from 0 to 900;
  - start fuel 10 gal, first station at 150, 300 mi → `START_FUEL_INSUFFICIENT`, `gap_start_mile == 100`, `gap_end_mile == 150`, `start_fuel_gallons == 10`, `gallons_short == 5`;
  - start fuel 0 and no station at mile 0 → `START_FUEL_INSUFFICIENT` with `gap_start_mile == 0`;
  - no node within 500 mi of the origin with a part-full tank → `STATION_GAP` from 0 (a full tank would not help), not `START_FUEL_INSUFFICIENT`;
  - `str(error)` contains the reason value and the gap miles; for start fuel it also contains the start fuel, the next fuel point and the gallons short (data-model.md examples);
  - an infeasible call returns nothing: the exception is raised, no `FuelPlan` is produced.
- [X] T008 [P] [US2] Extend `tests/unit/planner/test_oracle_agreement.py`: for every seed `0..49`, `oracle_cost is None` if and only if `plan_refuelling` raises `InfeasibleRoute`.

### Implementation for User Story 2

- [X] T009 [US2] In `planner/optimizer.py`, complete `InfeasibleRoute`: fields `reason`, `gap_start_mile`, `gap_end_mile`, `usable_range_miles`, `start_fuel_gallons` (`Decimal | None`, only for `START_FUEL_INSUFFICIENT`), `gallons_short` (`Decimal | None`, only for `START_FUEL_INSUFFICIENT`: `(gap_end − gap_start) / mpg`), and a readable `__str__` as in data-model.md. Make the origin check raise `STATION_GAP` when the window is empty even with a full tank. Run T007 and T008 green.

**Checkpoint**: US1 and US2 both work; every outcome is a plan or a detailed `InfeasibleRoute`.

---

## Phase 5: User Story 3 - Keep a safety reserve in the tank (Priority: P3, optional)

**Goal**: an optional `reserve_gallons` (0–25, default 0) the tank never drops below (FR-012). **Drop this phase first if time is short.**

**Independent Test**: `tests/unit/planner/test_reserve.py` passes.

### Tests for User Story 3 ⚠️ (write first, show failing)

- [X] T010 [P] [US3] Write `tests/unit/planner/test_reserve.py` (pure), covering:
  - reserve 5 on a multi-stop route → no leg between consecutive fuel points (start, each stop, finish) is longer than 450 mi; the tank never drops below 5 gal; `fuel_left_gallons ≥ 5`; fuel balance still exact;
  - reserve 5 with stations 470 mi apart → `STATION_GAP` with `usable_range_miles == 450`, while the same input with reserve 0 is feasible;
  - start fuel 4 with reserve 5 → `ValueError` (invalid input, not infeasible);
  - reserve `< 0`, `> 25`, or `≥ capacity` (e.g. reserve 20 with `max_range_miles=150`, capacity 15) → `ValueError`; a float reserve → `TypeError`;
  - reserve 0 gives a `FuelPlan` equal to the call without the argument (several inputs from `test_optimizer.py`).

### Implementation for User Story 3

- [X] T011 [US3] In `planner/optimizer.py`, implement the reserve per research R7: validate `0 ≤ reserve_gallons ≤ 25`, `reserve < capacity`, `reserve ≤ start_fuel_gallons`; run the same loop with usable capacity `max_range_miles − reserve × mpg` and usable start fuel `(start_fuel − reserve) × mpg`; add the reserve back to `fuel_left_gallons`; `usable_range_miles` in errors reflects the reserve. Run T010 green, and re-run all of `tests/unit/planner/`.

**Checkpoint**: all three stories work.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T012 Time `plan_refuelling` by hand (quickstart §4, SC-006): on the 202 real Dallas → Chicago candidates (Feature 002 quickstart §3, converted with `Decimal(float(m)).quantize(Decimal("0.001"))` as in the contract) and on a synthetic 3,000-mile list of ~400 stations. Target well under 10 ms. Note the figures and the machine.
- [ ] T013 [P] Update `README.md`:
  - status (003 done);
  - assumptions (constitution VI): the vehicle starts with a full tank unless told otherwise; no safety reserve by default, so the range is the brief's 500 miles (a production default of 5 gal would be sensible; the reserve is an option); each stop's cost is rounded half up to cents and the total is the sum of the rounded stops; prices are never rounded before multiplying; detour fuel is ignored;
  - in "How it works", two sentences on the greedy (buy just enough to reach a cheaper station, else fill up) with a link to `docs/algorithms/refuelling-greedy.md`;
  - the measured timing and machine from T012.
- [ ] T014 [P] Sync the docs: in `docs/algorithms/refuelling-greedy.md`, replace "Rounding: only at the API boundary" with "rounding happens once, when the plan is built (the money output); the API only formats" and mention fuel tracked in miles of range and the infeasible detail fields; in it and in `docs/adr/0001-greedy-refuelling-optimizer.md`, replace "under 1 ms" with the time measured in T012; in `docs/implementation-plan.md` Feature 003, sync the module/test names if they changed and tick "Done when".
- [ ] T015 Quality gate:
  - `python -m pytest --cov=planner --cov-report=term-missing` → `planner/optimizer.py` ≥ 95% (SC-007), whole suite green;
  - `ruff check .` and `ruff format --check .`;
  - `python manage.py check`.
- [ ] T016 Run the full quickstart.md validation (§1–§4) and confirm the outputs match the expected values there.

---

## Dependencies & Execution Order

- **Phase 1** (oracle) **→ Phase 2** (types, validation) **→ US1 → US2 → US3 → Phase 6.**
- **US1:** T004/T005 before T006.
- **US2:** depends on US1 (it completes the errors the greedy raises). T007/T008 before T009.
- **US3:** depends on US1 (same loop with shifted numbers). T010 before T011. Optional: skip it entirely if short on time; nothing else depends on it.
- All tasks in Phases 3–5 edit `planner/optimizer.py` sequentially; only the test files can be written in parallel.

### Parallel Opportunities

- **US1 tests:** T004 and T005.
- **US2 tests:** T007 and T008 (different files; T008 extends the US1 oracle file after T005).
- **Across stories, tests only:** T007 and T010 can be written while T006 is in progress.
- **Polish:** T013 and T014.

---

## Parallel Example: User Story 1

```bash
# Tests first, together:
Task: "Write tests/unit/planner/test_optimizer.py (T004)"
Task: "Write tests/unit/planner/test_oracle_agreement.py (T005)"

# Then the single implementation task:
Task: "Implement the greedy in planner/optimizer.py (T006)"
```

---

## Implementation Strategy

1. Phase 1 + Phase 2: the oracle, the types and validation.
2. **MVP: US1.** The cheapest plan, proven against the oracle. Commit as `feat(planner): greedy refuelling optimizer`.
3. US2: detailed infeasible results. Commit as `feat(planner): detailed infeasible-route errors`.
4. US3 (optional): the reserve. Commit as `feat(planner): optional fuel reserve`.
5. Phase 6: timing, README, docs and the quality gate. Commit as `docs: feature 003 results`.

## Notes

- `planner/optimizer.py` MUST NOT import Django or anything outside the standard library (constitution III); T002 checks it.
- Every number is a `Decimal`; a float raises `TypeError` (constitution V).
- `InfeasibleReason` is a `StrEnum`; no bare reason strings in code (constitution, technical constraints).
- Never assert timings in automated tests (SC-006 is measured by hand).
