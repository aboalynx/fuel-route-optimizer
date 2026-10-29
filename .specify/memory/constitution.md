<!--
Sync Impact Report
- Version change: (unversioned template) → 1.0.0
- Modified principles: template placeholders replaced with 8 project principles
  - I. Deterministic Results
  - II. Single External Routing Call
  - III. Pure Core
  - IV. Test-First, Offline Tests
  - V. Explicit Units and Decimal Money
  - VI. Documented Data Assumptions
  - VII. Simplicity Over Cleverness
  - VIII. Zero-Setup Reviewer Run
- Added sections: Core Principles (8), Technical Constraints, Development Workflow, Governance
- Removed sections: none
- Templates requiring updates: none (dependent templates read the constitution at runtime)
- Follow-up TODOs: none
-->

# Fuel Route Optimizer Constitution

## Core Principles

### I. Deterministic Results

The same request MUST always produce the same fuel plan, stops, and total cost.
The request path MUST NOT use an LLM, random number generation, or any other
non-deterministic source. Ties (for example, equally priced stations) MUST be broken by a
stable, documented rule.

**Rationale**: Reviewers and tests must be able to compare outputs exactly.

### II. Single External Routing Call

Each API request MUST make at most one call to the external routing service. Everything
else (station lookup, matching stations to the route, optimization, cost) MUST be computed
locally from pre-built data.

**Rationale**: Keeps latency low and predictable, and limits dependence on third-party
rate limits.

### III. Pure Core

Geometry, optimizer, and data-pipeline logic MUST be plain Python functions and modules
with no Django imports. Django is limited to the HTTP layer: request parsing, validation,
calling the core, and serializing the response.

**Rationale**: Pure functions are fast to test, easy to reason about, and reusable outside
the web framework.

### IV. Test-First, Offline Tests

Tests for pure logic MUST be written before the implementation and seen failing first.
Tests MUST NOT make real network calls; the routing client MUST be mocked or replaced with
recorded fixtures. A phase is complete only when its tests pass in CI.

**Rationale**: Offline tests are reliable and repeatable, and CI is the single source of
truth for "done".

### V. Explicit Units and Decimal Money

Distances MUST be in miles, fuel volume in gallons, and money in USD. Names, fields, or
types MUST make the unit explicit (for example, `distance_miles`, `price_usd_per_gallon`).
Prices and costs MUST use `decimal.Decimal`, never `float`, with rounding applied only at
the output boundary using a documented rule.

**Rationale**: Unit mix-ups and float rounding errors are the most likely sources of
wrong costs.

### VI. Documented Data Assumptions

Every assumption about input data or vehicle behavior MUST be written in the README. At a
minimum this covers: Canadian stations are excluded; when a station appears more than once
the minimum price is used; the vehicle starts with a full tank. New assumptions MUST be
added to the README in the same change that introduces them.

**Rationale**: Hidden assumptions make results impossible to verify.

### VII. Simplicity Over Cleverness

The project MUST NOT add services, queues, caches, background workers, or infrastructure
that the assignment does not require. Prefer the simplest algorithm and data structure that
meets the requirements; any added complexity MUST be justified in the plan.

**Rationale**: A small, readable solution is easier to review and less likely to break.

### VIII. Zero-Setup Reviewer Run

A reviewer MUST be able to clone, install, and run the project and its tests with no API
keys and no geocoding step. Pre-built station data (including coordinates) MUST be
committed or produced by an offline script, and a key-free routing option MUST be the
default.

**Rationale**: The reviewer's first run must succeed without accounts or setup.

## Technical Constraints

- Backend: Python with Django for the HTTP layer only (see Principle III).
- Station data is pre-processed offline into a committed artifact that is loaded at
  runtime; the request path never geocodes.
- Configuration that may vary (for example, vehicle range and MPG) MUST have documented
  defaults so the project runs without extra settings.

## Development Workflow

- Work proceeds in phases; each phase lists its tests and is complete only when they pass
  in CI.
- Every change is checked against these principles during review; violations MUST be fixed
  or explicitly justified in the plan's complexity tracking.
- README updates for data assumptions ship in the same change as the code (Principle VI).

## Governance

This constitution takes precedence over other project practices. Amendments MUST be made
through `/speckit-constitution`, recorded in the Sync Impact Report, and versioned with
semantic versioning: MAJOR for removing or redefining a principle, MINOR for adding a
principle or materially expanding guidance, PATCH for wording and clarifications. Plans
and reviews MUST include a constitution check against every principle above.

**Version**: 1.0.0 | **Ratified**: 2026-10-29 | **Last Amended**: 2026-10-29
