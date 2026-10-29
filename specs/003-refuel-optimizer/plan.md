# Implementation Plan: Refuel Optimizer

**Branch**: `003-refuel-optimizer` | **Date**: 2026-10-29 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/003-refuel-optimizer/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

This feature adds the money core of the planner: `plan_refuelling()` in `planner/optimizer.py`, a
pure function over `Decimal` values. It takes the route length, the stations along it (mile marker,
exact price, ID), the vehicle (mpg, range) and the start fuel, and returns the cheapest
`FuelPlan` or raises `InfeasibleRoute` with the gap and full details.

- **Algorithm:** the greedy "next strictly cheaper node, else fill up and go to the cheapest in
  range" from ADR-0001, with the origin priced +∞ and the destination priced 0 (research R1).
- **Exactness:** fuel is tracked in miles of range inside the loop, so every sum is exact for any
  mpg (R2). Each stop's cost is rounded half up to cents once; the total is the sum of the rounded
  stop costs (R3, spec Clarifications Q3).
- **Errors:** invalid input → `ValueError`/`TypeError` (HTTP 400 in 004); impossible trip →
  `InfeasibleRoute` with `STATION_GAP` or `START_FUEL_INSUFFICIENT` and the numbers behind it
  (HTTP 422 in 004) (R4, spec Clarifications Q1).
- **Proof by test:** a DP oracle on ~50 seeded small instances must agree on every case (R6).
- **Optional reserve:** the same loop with a smaller usable tank (R7); default 0 so the range stays
  the assignment's 500 miles.

## Technical Context

**Language/Version**: Python 3.15 (venv 3.15.2). Supported: 3.13–3.14 officially (Django 6.1.2), also CI-tested on 3.15.

**Primary Dependencies**: none new. `planner/optimizer.py` uses only the standard library (`decimal`, `dataclasses`, `enum`). Tests use pytest and `random.Random(seed)`.

**Storage**: none. The optimizer reads no data; Feature 004 passes the candidates in.

**Testing**: pytest, pure unit tests (no Django, no network), plus the DP oracle in `tests/unit/planner/oracle.py`.

**Target Platform**: developer laptop and the CI matrix (3.13, 3.14, 3.15).

**Project Type**: web service (Django). This feature adds one pure library module.

**Performance Goals**: a coast-to-coast plan with a few hundred candidates well under 10 ms (measured by hand, SC-006).

**Constraints**:

- exact `Decimal` arithmetic, no float (constitution V);
- deterministic, documented tie rule (constitution I);
- no Django, no I/O (constitution III);
- ≥ 95% coverage of `planner/optimizer.py` (SC-007).

**Scale/Scope**: 0–~400 stations per call; a 500-mile window holds at most ~150 of them.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle / rule | Check | Status |
| --- | --- | --- |
| I. Deterministic Results | Fixed tie rule (equal is not cheaper; farthest, then lowest `opis_id`); no randomness in the product; oracle cases are seeded | Pass |
| II. Single External Routing Call | No external call at all | Pass |
| III. Pure Core | `planner/optimizer.py` imports only the stdlib; an AST test checks there is no Django import | Pass |
| IV. Test-First, Offline Tests | Tests and the oracle are written first and seen failing; no network, no DB | Pass |
| V. Explicit Units and Decimal Money | `distance_miles`, `price_usd_per_gallon`, `gallons`, `cost_usd`; all `Decimal`; a float raises `TypeError`; rounding happens once, when the plan (the money output) is built, with a documented rule (R3) | Pass |
| VI. Documented Data Assumptions | README: full tank by default, no default reserve (500-mi range per the brief), detour fuel ignored, total = sum of rounded stops | Pass (README in this feature) |
| VII. Simplicity | One forward pass, no new dependency, no precomputed structures (R8) | Pass |
| VIII. Zero-Setup Reviewer Run | Nothing to set up | Pass |
| Technical Constraints: enums | `InfeasibleReason` `StrEnum` | Pass |
| Technical Constraints: services | No Django logic here; the request service that calls it is Feature 004 | Pass |

**Post-design re-check:** all gates still pass. One wording point: the algorithm doc says rounding
happens "only at the API boundary"; this plan rounds when the `FuelPlan` is built, which is the
money output boundary (nothing computes with the rounded costs afterwards). The algorithm doc is
updated in this feature to say so. No complexity to justify.

## Project Structure

### Documentation (this feature)

```text
specs/003-refuel-optimizer/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/refuel_optimizer.md
├── checklists/requirements.md
└── tasks.md            # /speckit-tasks
```

### Source Code (repository root)

```text
planner/
└── optimizer.py                 # PlanStation, FuelPurchase, FuelPlan, InfeasibleReason (StrEnum),
                                 # InfeasibleRoute, round_cents, plan_refuelling

tests/unit/planner/
├── oracle.py                    # DP over (station, whole fuel units) on small integer instances
├── test_optimizer.py            # hand-worked scenarios, errors, invariants, reserve, purity (AST)
└── test_oracle_agreement.py     # ~50 seeded random cases: cost and feasibility match the oracle
```

**Structure Decision**: the optimizer joins the existing pure `planner/` package next to
`corridor.py`. It does not import `corridor` (its input is its own `PlanStation`), so the two
stay independent; Feature 004's request service converts candidates and reads the vehicle settings.

## Implementation notes for `/speckit-tasks`

- **TDD order:**
  1. the oracle (`oracle.py`) with a few tiny hand-checked cases of its own;
  2. `test_optimizer.py`: types and purity, validation (`ValueError`/`TypeError`), then the
     scenarios: no stops under range (and exactly 500 mi), buy-to-cheaper, fill-up, buy-to-finish
     (destination sentinel regression), the tie rule (farthest, then lowest ID), exact money with an
     8-dp price and total = sum of rounded stops, fuel balance and tank bounds, station gap
     (including no stations), start fuel insufficient with all details, start fuel 0 with and
     without a station at mile 0, zero-length route;
  3. `planner/optimizer.py` until green;
  4. `test_oracle_agreement.py` (~50 seeds), fix until it agrees on every case;
  5. reserve tests (US3: no leg > 450 mi with reserve 5, 470-mi gap infeasible, start below
     reserve invalid, reserve 0 identical), then the reserve code. Drop this step first if short
     on time;
  6. timing by hand, README, algorithm doc wording on rounding.
- **README:** add the assumptions (full tank default, no default reserve and why, total = sum of
  rounded stop costs, detour fuel ignored) and the measured timing.

## Complexity Tracking

No constitution violations. Nothing to justify.
