# Feature Specification: Refuel Optimizer

**Feature Branch**: `003-refuel-optimizer`

**Created**: 2026-10-29

**Status**: Draft

**Input**: User description: "merge to main then run specify for next feature 3". The feature content is the Feature 003 Specify input in `docs/implementation-plan.md`: "Given a route of known length, an ordered list of fuel stations along it (mile marker and price per gallon), a vehicle with a fixed miles-per-gallon and maximum range (10 mpg, 500 miles, so a 50-gallon tank), and the fuel in the tank at the start (default full), compute the fuel purchase plan with the lowest total cost that gets the vehicle from start to finish without running dry. The plan lists each stop in route order with gallons bought and cost; stops where nothing is bought are omitted. It returns total gallons consumed, gallons purchased and total cost. Fuel can only be bought at stations (not at the start or finish), in any fractional amount, and the tank never exceeds capacity. Money is exact and rounded to cents only for display. Ties between equally priced stations follow a fixed, documented rule. If any stretch of the route (including from the start with the given start fuel) is longer than the vehicle can cover, the plan is infeasible and the result says where the gap starts and ends. Optional extra (lowest priority; the first optimizer extra to drop if time is short): a safety reserve in gallons (default 0, range 0-25) that the vehicle never dips below. The start fuel must be at least the reserve. Acceptance: a trip under 500 miles with a full tank has no stops and zero cost; when a cheaper station is within range the vehicle buys only enough to reach it; when the finish is within range and no cheaper station precedes it, the vehicle buys only enough to reach the finish; fuel balance holds (start + purchased - left = distance / mpg); on small random instances the cost equals a brute-force optimum; with a reserve of 5 gallons, no leg between consecutive fuel points exceeds 450 miles."

## Clarifications

### Session 2026-10-29

- Q: What range of start fuel should the planner accept, and should a 5-gallon safety margin apply by default? → A: Start fuel is optional and defaults to a full tank (50 gal); 0 to tank capacity is accepted. There is no safety margin by default, so the range is the assignment's 500 miles. The 5-gallon margin is the optional reserve (0–25, default 0) that the caller can turn on. A start fuel that cannot reach the first fuel point is reported as infeasible with full details: start fuel, the miles it covers, the miles to the next fuel point and the gallons short.
- Q: When several stations within range share the same lowest price, which one should the truck go to? → A: An equal price is not cheaper. Among the equally cheapest stations in range, the farthest is chosen, then the lowest station ID.
- Q: How should the total cost be rounded to cents relative to the cost of each stop? → A: Each stop's cost is computed exactly and rounded half up to cents; the total is the sum of the rounded stop costs, so the stops always add up to the total shown. Prices stay exact (up to 8 decimal places, as stored) and are never rounded to cents before multiplying.

## User Scenarios & Testing *(mandatory)*

The users of this feature are the route-plan endpoint (Feature 004), which passes it the candidate
stations found by Feature 002, and, through that endpoint, a driver or dispatcher who wants the
cheapest way to fuel a trip. A developer or reviewer exercises it directly through tests.

### User Story 1 - Get the cheapest fuel plan for a trip (Priority: P1) 🎯 MVP

Given the route length, the stations along it (mile marker, price per gallon, station ID), the
vehicle (10 mpg, 500-mile range, so a 50-gallon tank) and the fuel in the tank at the start (full by
default), the planner returns the fuel purchase plan with the lowest total cost that reaches the
finish without running dry. The plan lists each stop in route order with the gallons bought there
and their cost, plus the total gallons used, the total gallons bought, the total cost and the fuel
left at the finish.

**Why this priority**: the cheapest plan is the answer the whole project exists to give. Features 002
and 004 only feed it and present it.

**Independent Test**: with hand-made station lists (no route service, no station data, no network),
check the stops, gallons and costs against values worked out by hand, and on small random instances
against an exhaustive search for the cheapest plan.

**Acceptance Scenarios**:

1. **Given** a 400-mile trip and a full tank, **When** a plan is requested, **Then** it has no stops, 0 gallons bought and a total cost of $0.00.
2. **Given** the vehicle is at a station and a strictly cheaper station lies within range ahead, **When** a plan is requested, **Then** it buys only enough fuel at the current station to reach the cheaper one (nothing if it already has enough).
3. **Given** the vehicle is at a station with no cheaper station within range and the finish beyond range, **When** a plan is requested, **Then** it fills the tank there and drives to the cheapest station within range.
4. **Given** the finish is within range and no cheaper station comes before it, **When** a plan is requested, **Then** the vehicle buys only enough to reach the finish, so it does not finish with fuel it paid for but did not need.
5. **Given** any feasible plan, **When** it is returned, **Then** fuel balance holds exactly: start fuel + gallons bought − fuel left = route length ÷ mpg.
6. **Given** two stations at the same lowest price within range, at miles 200 and 300, **When** the planner picks where to go next, **Then** it goes to the one at mile 300 (the farthest); if both are at the same mile, the lower station ID wins, and the same input always gives the same plan.
7. **Given** small random trips (a handful of stations, whole-number miles and prices), **When** a plan is requested, **Then** its total cost equals the cheapest cost found by an exhaustive search, on every one of about 50 fixed (seeded) cases.
8. **Given** a station price with more than two decimal places (for example $3.00733333), **When** costs are computed, **Then** they are exact; rounding to cents happens only for the reported stop costs, and the total cost is the sum of the rounded stop costs.

---

### User Story 2 - Learn exactly where a trip is impossible (Priority: P2)

When the vehicle cannot complete the trip, because the start fuel does not reach the first station
or a stretch of the route between fuel points is longer than the vehicle's range, the planner says
so clearly. The result names the reason and where the gap starts and ends (in miles from the start),
instead of returning a partial or misleading plan.

**Why this priority**: a wrong "plan" on an impossible route would strand the driver. Real routes can
have long stretches with no US station (remote areas, or a detour through Canada), so this case
will happen.

**Independent Test**: with hand-made station lists containing a gap longer than 500 miles, or a low
start fuel, check that the result is "infeasible" with the right reason and gap miles.

**Acceptance Scenarios**:

1. **Given** stations at miles 100 and 700 on an 800-mile route, **When** a plan is requested, **Then** it is infeasible because of a station gap from mile 100 to mile 700.
2. **Given** a 900-mile route with no stations at all, **When** a plan is requested, **Then** it is infeasible because of a station gap from mile 0 to mile 900.
3. **Given** a start fuel of 10 gallons (100 miles) and the first station at mile 150, **When** a plan is requested, **Then** it is infeasible because the start fuel is insufficient, from mile 100 (where the fuel would run out) to mile 150 (the next fuel point). The result also states the start fuel (10 gal), the miles it covers (100), the miles to the next fuel point (150) and the gallons short (5).
4. **Given** a start fuel of 0 and a station at mile 0, **When** a plan is requested, **Then** the vehicle buys fuel there and the trip can proceed. With a start fuel of 0 and no station at mile 0, the trip is infeasible because the start fuel is insufficient.
5. **Given** an infeasible trip, **When** the result is returned, **Then** no plan, stops or cost are returned with it.

---

### User Story 3 - Keep a safety reserve in the tank (Priority: P3, optional)

The driver can ask the planner never to let the tank drop below a reserve of fuel (0 to 25 gallons,
default 0). The plan then treats only the fuel above the reserve as usable, so the effective range
shrinks: with a 5-gallon reserve, no leg between consecutive fuel points is longer than 450 miles.

**Why this priority**: it is useful but not part of the assignment. It is the first optimizer extra to
drop if time is short.

**Independent Test**: with a reserve of 5 gallons on hand-made station lists, check that no leg
between consecutive fuel points (start, stops, finish) exceeds 450 miles, and that the fuel left at
the finish is at least the reserve.

**Acceptance Scenarios**:

1. **Given** a reserve of 5 gallons, **When** a plan is requested, **Then** no leg between consecutive fuel points (start, each stop, finish) is longer than 450 miles, and the tank never drops below 5 gallons.
2. **Given** a reserve of 5 gallons and stations 470 miles apart, **When** a plan is requested, **Then** it is infeasible (station gap), although it would be feasible with no reserve.
3. **Given** a start fuel below the reserve, **When** a plan is requested, **Then** the request is rejected as invalid input, not as an infeasible route.
4. **Given** a reserve of 0 (the default), **When** a plan is requested, **Then** the plan is identical to the plan with no reserve option at all.

---

### Edge Cases

- **Trip exactly at range.** A 500-mile trip with a full tank needs no stop (the limit is inclusive), and the vehicle arrives with 0 gallons.
- **Station at the start or the finish.** A station at mile 0 can be used to buy fuel. A station at the finish mile is never worth buying at, because buying stops once the finish is reachable.
- **Several stations at the same mile.** They are all considered; the tie rule decides which one is used.
- **Stations with equal prices.** Equal is not cheaper, so the vehicle never stops to buy at a station that is only as cheap as the one it is at.
- **Station list not in order.** The input must be in route order (by mile marker, then station ID), as Feature 002 returns it. Stations outside the route (mile below 0 or beyond the finish) are invalid input.
- **Zero-length or tiny trips.** A route of 0 miles has no stops and zero cost.
- **Close stops.** A purely cost-optimal plan can include two stops close together for a small saving. This is allowed; a minimum saving per stop is future work.
- **Detour fuel ignored.** Fuel used to drive from the route to an off-route station and back is not counted (project assumption).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST compute, for a route of known length, a list of stations along it and a vehicle, the fuel purchase plan with the lowest total cost that reaches the finish without the tank running dry.
- **FR-002**: The vehicle MUST be described by its miles per gallon and its maximum range in miles (defaults 10 mpg and 500 miles). The tank capacity MUST be derived as range ÷ mpg (50 gallons by default), not configured separately.
- **FR-003**: The start fuel MUST be accepted from 0 up to the tank capacity, and MUST default to a full tank. Values outside that range MUST be rejected as invalid input.
- **FR-004**: Fuel MUST be bought only at stations, never at the start or the finish, in any fractional amount, and the tank MUST never hold more than its capacity.
- **FR-005**: The plan MUST list each stop where fuel is bought, in route order, with the station ID, its mile marker, its price per gallon, the gallons bought and the cost. Stations where nothing is bought MUST NOT appear.
- **FR-006**: The plan MUST report the total gallons consumed (route length ÷ mpg), the total gallons purchased, the total cost and the fuel left at the finish. Fuel balance MUST hold exactly for the configured mpg (10 by default, and any mpg that divides a power of ten): start fuel + purchased − left = consumed. For other mpg values it MUST hold to within 1e-20 gallons, because a gallon figure such as 100 ÷ 3 cannot be written exactly.
- **FR-007**: When the vehicle is at a fuel point and a strictly cheaper station lies within range, it MUST buy only enough to reach the first such station. When none does and the finish is within range, it MUST buy only enough to reach the finish. Otherwise it MUST fill the tank and continue to the cheapest station within range.
- **FR-008**: Ties MUST follow one fixed, documented rule: an equal price is not cheaper; among equally cheapest stations within range, the farthest is chosen, then the lowest station ID. The same input MUST always give the same plan.
- **FR-009**: Money MUST be computed exactly from the stations' unrounded prices (up to 8 decimal places); prices are never rounded to cents before multiplying by gallons. Each stop's cost MUST be rounded to whole cents (half up) only when reported, and the total cost MUST be the sum of the rounded stop costs, so the stops always add up to the total shown.
- **FR-010**: If any stretch between consecutive fuel points (the start, each station, the finish) is longer than the vehicle's range, the system MUST report the trip as infeasible with the reason "station gap" and the start and end of the gap in miles. It MUST NOT return a partial plan.
- **FR-011**: If the start fuel cannot reach the first fuel point the vehicle needs, the system MUST report the trip as infeasible with the reason "start fuel insufficient", giving the mile where the fuel would run out (the gap start) and the mile of that next fuel point (the gap end). The result MUST also state the start fuel in gallons, the miles it covers, the miles to the next fuel point and the gallons short, so a user or developer can see why without re-computing it.
- **FR-012** *(optional; first extra to drop)*: The system MUST accept a reserve of 0 to 25 gallons (default 0) that the tank never drops below. The reserve MUST also be less than the tank capacity. The start fuel MUST be at least the reserve, otherwise the request is invalid input. With a reserve, the usable capacity is capacity − reserve, so the effective range is (capacity − reserve) × mpg; a reserve of 0 MUST give exactly the plan without a reserve.
- **FR-013**: The optimizer MUST make no external calls and read no stored data. It works only on the values it is given, so it can be tested on its own and gives the same answer every time.
- **FR-014**: Input that cannot describe a real trip (negative length, station mile markers outside the route, stations out of route order, non-positive mpg or range, non-positive prices) MUST be rejected as invalid input, distinct from an infeasible route.

### Key Entities

- **Vehicle**: miles per gallon, maximum range in miles, and the derived tank capacity in gallons.
- **Plan station**: a station ID, its mile marker along the route and its exact price per gallon (shaped like Feature 002's candidate; the off-route distance is not used here).
- **Fuel purchase**: one stop in the plan: station ID, mile marker, price per gallon, gallons bought and cost.
- **Fuel plan**: the ordered purchases, total gallons consumed, total gallons purchased, total cost and fuel left at the finish.
- **Infeasible route**: the result when the trip cannot be completed: a reason ("station gap" or "start fuel insufficient"), the start and end mile of the gap, and, for "start fuel insufficient", the start fuel, the miles it covers, the miles to the next fuel point and the gallons short.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On about 50 fixed random small trips, the plan's total cost equals the cheapest cost found by an exhaustive search in 100% of cases.
- **SC-002**: Every feasible plan in the tests satisfies fuel balance exactly, with no rounding difference, and never lets the tank exceed capacity or drop below 0 (or below the reserve).
- **SC-003**: Every hand-worked scenario in the acceptance scenarios gives exactly the expected stops, gallons and costs, to the cent.
- **SC-004**: Every infeasible test trip is reported with the correct reason and gap miles, and none returns a plan.
- **SC-005**: Running the same request twice gives identical plans, including stop order and cost.
- **SC-006**: Planning a coast-to-coast trip with several hundred candidate stations is instant for the user (well under 10 ms on a typical laptop), measured by hand, not asserted in automated checks.
- **SC-007**: The optimizer's automated tests cover at least 95% of its logic.

## Assumptions

- **Model.** The plan is cost-optimal for the stated model only: fuel used for detours to off-route stations, the number of stops, minimum purchase amounts and time are ignored (README assumptions).
- **Inputs.** Candidates come from Feature 002, already sorted by mile marker then station ID, with exact prices from Feature 001. The route length is the routing service's distance.
- **Start fuel.** The vehicle starts with a full tank unless told otherwise (constitution, Principle VI).
- **Prices.** A station's price is its effective price from Feature 001 (the minimum when a station appears more than once).
- **Infeasible versus invalid.** "Infeasible" means the inputs are valid but the trip cannot be completed; "invalid" means the inputs cannot describe a real trip. Feature 004 maps them to HTTP 422 and 400 respectively, with the reason and the details in the response body.
- **No default safety margin.** The assignment fixes the range at 500 miles, so the reserve defaults to 0. The README notes that a production default of 5 gallons would be sensible, and the demo shows a request with a 5-gallon reserve.
- **Out of scope.** Finding stations along the route (Feature 002); the HTTP endpoint, error mapping and map (Feature 004); a minimum saving per stop (future work).
