# ADR-0001: Greedy "next cheaper station" refuelling optimizer

- Status: Accepted · Date: 2026-10-29
- Related: [refuelling-greedy.md](../algorithms/refuelling-greedy.md), Feature 003, F3/F4/F5

## Context

With stations projected onto a fixed route, choosing where to refuel and how much to buy is a
one-dimensional optimisation. It must be:

- optimal;
- deterministic (constitution I);
- fast;
- exact in `Decimal` (constitution V);
- simple enough to explain.

Inputs are typically 100–400 candidate stations.

## Decision

Use the classic greedy algorithm for the gas station problem on a line:

- **A strictly cheaper station is within range:** buy just enough to reach the first one.
- **Otherwise:** fill the tank and go to the cheapest station in range.

The origin is priced `+∞` (no purchase is possible there) and the destination `0`, so one rule
covers the start, the finish and infeasibility. Ties: equal is not cheaper; among equal cheapest
stations, the farthest wins, then the lowest `opis_id`.

## Rejected alternatives

| Option | Why not |
| --- | --- |
| DP over discretised fuel levels | Same answer, more code, awkward with `Decimal`. Kept as the test oracle |
| Linear programming | Needs a solver and floats; overkill for a problem with an exact greedy |
| Graph shortest path (general gas-station problem) | Built for route choice; our route is fixed |
| Heuristics ("refuel below ¼ tank") | Not optimal |
| LLM/ML ranking | Non-deterministic |

## Consequences

- Provably optimal for the model, `O(n·w)`, about 1 ms (measured 0.8 ms on 202 real candidates, 1.2 ms on 400). Pure and easy to test.
- Infeasibility maps cleanly to a real gap (HTTP 422).
- Ignores detour fuel, stop count and minimum purchase. Adding those would need the DP or a graph formulation.
- Correctness at the finish depends on the destination sentinel. A regression test guards it.
