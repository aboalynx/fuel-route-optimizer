# Feature Specification: Route Plan API

**Feature Branch**: `004-route-plan-api`

**Created**: 2026-10-29

**Status**: Draft

**Input**: User description: "ok merge then run specify for next feature". The feature content is the Feature 004 Specify input in `docs/implementation-plan.md` (endpoint, map page, error statuses, acceptance and decided details), updated for what Features 002 and 003 shipped: the optional reserve shipped in 003, so it is part of the request; an impossible trip (station gap or start fuel too low) returns 422 with the details 003 provides. Added at the user's request: a minimum saving per stop, so the plan does not stop for a few cents (User Story 6).

## Clarifications

### Session 2026-10-29

- Q: Should the plan avoid stops that save only a few cents? → A: Yes, as an option. A stop stays in the plan only if dropping it would raise the total cost by at least `min_saving_per_stop_usd`. Only the plan's own stops are considered for dropping, never other stations, so the extra cost is bounded and visible in the response. On the real Dallas → Chicago route, with 5 USD, this turns 4 stops ($134.64) into 2 stops ($134.81).
- Q: What should the default minimum saving per stop be? → A: 0 (off), range 0–100 USD. The default response is the provable minimum-cost plan that the oracle checks. The option is documented in the README and shown in the Postman collection with `min_saving_per_stop_usd = 5` (Dallas → Chicago: drops the 7¢ and 10¢ stops for 17¢ more).
- Q: How many decimal places should the response show for price per gallon and gallons? → A: Price per gallon exact as stored (up to 8 dp), gallons 4 dp, money 2 dp (ROUND_HALF_UP); total cost = sum of the rounded per-stop costs, unchanged. Tests check `abs(gallons × price − cost) ≤ 0.005` per stop, not equality. D10 in `docs/implementation-plan.md` and the README API example use these precisions.
- Q: When should a start and finish count as "the same location"? → A: When both coordinates are equal after rounding to 4 decimal places (the route-cache key) → 400 `same_location`. Plus a zero-length guard: if the routed distance or the route geometry length is below 0.01 mile, also 400 `same_location`, before the corridor search, so mile-marker rescaling never divides by zero. Never a 500.

## User Scenarios & Testing *(mandatory)*

The users are a dispatcher (or any API client, such as Postman) who wants the cheapest fuel plan for
a US truck trip, and a reviewer who checks the service through the API and the map page.

### User Story 1 - Plan a trip through the API (Priority: P1) 🎯 MVP

A dispatcher sends a start and a finish, each either a "City, ST" string or a latitude/longitude
pair, and gets back in one response: the resolved locations, a summary (distance, gallons, total
fuel cost, stops), the recommended stops in route order with gallons and cost, a map-ready route
with the stops on it, and metadata showing how many external routing calls were made and how long
each step took.

**Why this priority**: this is the assignment's deliverable. Everything built so far exists to answer
this request.

**Independent Test**: with the routing service replaced by a recorded response and a small station
fixture (no network), post a request and check the status, the response shape, the stops, the
totals, and that exactly one routing call was made.

**Acceptance Scenarios**:

1. **Given** start "Dallas, TX" and finish "Chicago, IL", **When** the request is sent, **Then** the response is 200 with the resolved start and finish, the summary, the stops in route order, a map feature collection (route line plus one numbered point per stop) and metadata with routing calls = 1 and cached = false.
2. **Given** start and finish as latitude/longitude pairs, **When** the request is sent, **Then** the result is the same kind of 200 response, with the coordinates echoed back as the resolved locations.
3. **Given** any successful response, **When** the stop costs are added up, **Then** they equal the total fuel cost exactly, to the cent.
4. **Given** optional start fuel, corridor radius and reserve values within their ranges, **When** the request is sent, **Then** they are used and echoed in the summary's assumptions; when omitted, the defaults (full tank, 10 miles, 0 gallons) are used and echoed.
5. **Given** a trip shorter than the range on a full tank, **When** the request is sent, **Then** the response is 200 with no stops and a total cost of 0.00.
6. **Given** the same request sent twice, **When** both responses are compared, **Then** the plans (stops, gallons, costs, totals) are identical.

---

### User Story 2 - Repeat requests without calling the routing service again (Priority: P1)

When the same route is requested again within 24 hours, the service reuses the stored route instead
of calling the routing service, and the response says so. The plan itself is recomputed and is
identical.

**Why this priority**: the brief asks for as few routing calls as possible and for fast responses. A
repeat request with zero external calls shows both.

**Independent Test**: send the same request twice with a mocked routing service; the second
response reports cached = true and routing calls = 0, the mock was called once, and the plans are
identical.

**Acceptance Scenarios**:

1. **Given** a request that was answered successfully, **When** the same start and finish are requested again within 24 hours, **Then** routing calls = 0, cached = true, and the plan is identical to the first.
2. **Given** a cached route, **When** a different start fuel, radius or reserve is requested for the same start and finish, **Then** the route still comes from the cache (0 calls), and the plan reflects the new values.
3. **Given** two coordinate pairs that differ only beyond the 4th decimal place, **When** both are requested, **Then** they share one cached route.
4. **Given** the routing service failed for a request, **When** the same request is repeated, **Then** the service tries the routing service again (failures are never cached).

---

### User Story 3 - Clear errors for every failure (Priority: P2)

Every failure returns a consistent JSON error body with a stable code, a readable message and,
where useful, details, so both a user and a developer can see what went wrong without reading the
logs.

**Why this priority**: the clarified 003 behaviour (detailed infeasible results) and the review of the
assignment depend on errors that explain themselves.

**Independent Test**: one request per error case, each checked for its status, code, message and
details. No network.

**Acceptance Scenarios**:

1. **Given** a malformed body (missing finish, wrong types, latitude 200), **When** it is sent, **Then** 400 `invalid_input`, with the message naming the bad field.
2. **Given** start fuel above the tank capacity, a radius outside 1–25, a reserve outside 0–25, or start fuel below the reserve, **When** it is sent, **Then** 400 `invalid_input` naming the field.
3. **Given** "Dallas, Texas", **When** it is sent, **Then** 400 `location_not_found`, with a message that a 2-letter state code is expected.
4. **Given** an unknown city ("Atlantis, TX"), **When** it is sent, **Then** 400 `location_not_found` naming the input.
5. **Given** coordinates in Mexico City, or a non-US state code, **When** it is sent, **Then** 400 `location_outside_us`.
6. **Given** a start and finish that resolve to the same point (equal after rounding to 4 decimal places), **When** it is sent, **Then** 400 `same_location`, with no routing call.
7. **Given** two points about 1 m apart across a rounding boundary (latitude 32.78004999 vs 32.78005001), so their rounded coordinates differ, **When** the routing service returns a route shorter than 0.01 mile, **Then** 400 `same_location` from the zero-length guard, never a 500.
8. **Given** two points about 1 mile apart, **When** it is sent, **Then** 200 with 0 stops.
9. **Given** a route with a stretch longer than the vehicle range and no station, **When** it is sent, **Then** 422 `infeasible_route` with the reason "station gap", the gap's start and end mile and the coordinates of both ends on the route, and the usable range.
10. **Given** a start fuel too low to reach the first fuel point, **When** it is sent, **Then** 422 `infeasible_route` with the reason "start fuel insufficient", the gap miles, the start fuel, the reserve in force and the gallons short.
11. **Given** the routing service times out, fails, rate-limits or finds no route, **When** it is sent, **Then** 503 `routing_unavailable` with the reason and a retry hint (the service's suggested wait when it gave one, otherwise a default).
12. **Given** station data has not been loaded, **When** a request is sent, **Then** 503 with a message saying station data must be loaded.

---

### User Story 4 - See the plan on a map (Priority: P2)

A user opens one web page, enters a start and a finish, and sees the route on an OpenStreetMap map
with a numbered marker for each stop (name, price, gallons, cost) and a summary panel (distance,
total cost, stops, routing calls, total time). Errors from the API are shown as a readable message.

**Why this priority**: the brief asks for "a map of the route" and the Loom demo needs something to
show; the API alone already returns map-ready data, so the page is a thin viewer.

**Independent Test**: the page loads with status 200 and contains the form; by hand, Dallas →
Chicago and New York → Los Angeles render with their stops.

**Acceptance Scenarios**:

1. **Given** the page is opened, **When** it loads, **Then** it shows a form for start and finish (and the optional values) and an empty map, with no API key and no build step.
2. **Given** a valid start and finish, **When** the form is submitted, **Then** the route line and numbered stop markers appear, each marker shows name, price, gallons and cost, and the summary panel shows distance, total cost, stops, routing calls and total time.
3. **Given** the API returns an error, **When** the form is submitted, **Then** the page shows the error message instead of a map update.

---

### User Story 5 - Plan through a GET request (Priority: P3, optional)

The same request can be made with query parameters (for example from a browser address bar). This is
optional and the first thing to drop if time is short.

**Acceptance Scenarios**:

1. **Given** the same inputs as a POST, **When** they are sent as query parameters, **Then** the response is identical to the POST response (apart from timings and the cached flag).

---

### User Story 6 - Skip stops that barely save money (Priority: P2)

A purely cost-optimal plan can tell the driver to stop for 1.3 gallons to save 10 cents, because it
counts only fuel cost, not the time and hassle of a stop. The dispatcher can set a minimum saving per
stop (`min_saving_per_stop_usd`, default 0 = off): a stop stays in the plan only if dropping it would cost at least that much more.
The response says how many stops were dropped and how much more the plan costs than the cheapest
possible plan, so the trade-off is visible.

**Why this priority**: the real Dallas → Chicago plan has 4 stops, two of which save 7 and 10 cents.
With the rule it has 2 stops for 17 cents more, which is what a driver would actually do. The brief
says "optimal mostly means cost effective", which leaves room for this.

**Independent Test**: with hand-made station lists (no network), check which stops are dropped for a
given minimum saving, that every remaining stop saves at least that much, and that a minimum of 0
gives the cheapest plan unchanged.

**Acceptance Scenarios**:

1. **Given** a cheapest plan with a stop that saves $0.10, **When** the minimum saving is $5, **Then** that stop is dropped, the gallons are bought at the other stops, and the response shows 1 stop dropped and the extra cost ($0.10 or less).
2. **Given** any plan returned with a minimum saving of X, **When** any one of its stops is removed (keeping the others), **Then** the plan either becomes impossible or costs at least X more.
3. **Given** a minimum saving of 0, **When** the request is sent, **Then** the plan is exactly the cheapest plan (as in Feature 003) and the response shows 0 stops dropped and $0.00 extra.
4. **Given** a stop that cannot be dropped because the remaining stops could not get the truck to the finish, **When** the minimum saving is high, **Then** the stop stays, however little it saves.
5. **Given** two stops that save the same small amount, **When** one must be dropped first, **Then** the one with the smaller saving goes first, then the earlier mile, then the lower station ID, so the result is always the same.
6. **Given** a minimum saving outside 0–100 dollars, **When** the request is sent, **Then** 400 `invalid_input`.

---

### Edge Cases

- **Long routes.** A coast-to-coast route can have tens of thousands of points; the map line is thinned for the response (at most about 5,000 points) while stops, distance and costs come from the full route.
- **Full state names and lowercase codes.** "Dallas, Texas" is rejected with a hint; "dallas, tx" is accepted (case-insensitive).
- **Border coordinates.** Coordinates count as inside the USA when the nearest US populated place is within 25 miles; a point just across the border can therefore be accepted (documented assumption).
- **Same city twice.** "Dallas, TX" to "Dallas, TX" is `same_location`, not a zero-length plan.
- **Nearly the same point.** Two points whose rounded coordinates differ but whose route is shorter than 0.01 mile (for example both snap to the same road point) are `same_location` via the zero-length guard, checked before the station search; the request never fails with a server error.
- **Routing service down.** Requests fail fast with 503 within the routing timeout; nothing is cached.
- **Cache and plan inputs.** The cache stores the route only, never the plan, so a cached route with different start fuel, radius or reserve gives the plan for those values.
- **Close stops.** Stops that save less than the minimum saving are dropped (User Story 6). The rule only removes stops from the cheapest plan; it never looks for a different set of stations, so it gives fewer stops, not always the fewest possible. With 0 it is off.
- **Dropping the last needed stop.** A stop that the trip cannot do without is never dropped, whatever the threshold.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST expose one route-planning endpoint that accepts a start and a finish, each either a "City, ST" string or a latitude/longitude pair, plus optional start fuel (gallons, 0 to tank capacity, default full), corridor radius (miles, 1–25, default 10), reserve (gallons, 0–25, default 0) and minimum saving per stop (`min_saving_per_stop_usd`, USD, 0–100, default 0 = off, so the default response is the cheapest plan).
- **FR-002**: "City, ST" MUST be resolved locally from the shipped place data, case-insensitively, with a 2-letter state code. A full state name or unknown city MUST return `location_not_found`; the message for a non-2-letter state MUST say a 2-letter code is expected.
- **FR-003**: Coordinates MUST be accepted as inside the USA only when the nearest known US populated place is within 25 miles; otherwise, and for a non-US state code, the response MUST be `location_outside_us`.
- **FR-004**: Each request MUST make at most one external routing call, and none when the same route (same provider and start/finish coordinates rounded to 4 decimal places) was fetched successfully in the last 24 hours. A cached route MUST NOT change the plan, and failures MUST NOT be cached.
- **FR-005**: A successful response MUST contain: the resolved start and finish (query and coordinates); a summary with distance in miles, total gallons consumed, gallons purchased, total fuel cost in USD, number of stops, the number of stops dropped and the extra cost compared with the cheapest plan, and the assumptions used (mpg, range, tank capacity, start fuel, corridor radius, reserve, minimum saving per stop); the stops in route order with sequence number, station ID, name, address, city, state, coordinates, coordinate source, mile marker, distance off route, price per gallon, gallons and cost; a GeoJSON feature collection with the route line and one numbered point per stop; and metadata with the routing provider, the number of external routing calls, whether the route was cached, the number of candidate stations considered and per-step timings in milliseconds.
- **FR-006**: Numbers in responses MUST use these precisions: money (stop costs, total, extra cost) rounded half up to cents (2 dp); gallons to 4 dp; price per gallon exact as stored (up to 8 dp). Each stop's cost and the total MUST match the optimizer's values, so the stop costs add up to the total exactly (total = sum of the rounded per-stop costs). For every stop, shown gallons × shown price MUST be within 0.005 USD of the shown cost (at the default 10 mpg the shown gallons are exact, so only the cent rounding differs). Field names MUST carry units (for example `distance_miles`, `total_fuel_cost_usd`).
- **FR-007**: The same request MUST always return the same plan (stops, gallons, costs, totals).
- **FR-008**: Every error MUST return the body `{"error": {"code", "message", "details"}}` with a stable code from a fixed set: `invalid_input` (400), `location_not_found` (400), `location_outside_us` (400), `same_location` (400), `infeasible_route` (422), `routing_unavailable` (503), and a station-data-missing code (503).
- **FR-009**: `infeasible_route` details MUST include the reason, the gap's start and end mile, the coordinates of both ends on the route, and the usable range; for "start fuel insufficient" also the start fuel, the reserve in force and the gallons short.
- **FR-010**: `routing_unavailable` MUST include the routing reason and a retry hint (a `Retry-After` header): the service's suggested wait when it gave one, otherwise a default of 30 seconds.
- **FR-011**: The map line MUST be thinned to at most about 5,000 points for the response, keeping the first and last points; distances, stops and costs MUST come from the full route.
- **FR-012**: A web page MUST let a user enter a start and finish and show the route on an OpenStreetMap map with numbered stop markers (name, price, gallons, cost), a summary panel (distance, total cost, stops, routing calls, total time) and readable error messages, with no API key and no frontend build step.
- **FR-013** *(optional; first to drop)*: The endpoint MAY also accept the same inputs as query parameters on a GET request, returning the same response as the POST.
- **FR-014**: All endpoint behaviour MUST be testable without network access (recorded routing responses, a small station fixture).
- **FR-015**: Starting from the cheapest plan, the system MUST repeatedly drop the stop whose removal raises the total cost the least (ties: smaller saving, then earlier mile, then lower station ID), as long as that increase is below the minimum saving per stop and the trip stays possible without it, re-planning over the remaining stops each time. Only the plan's own stops may be dropped; no other station is brought in. Every stop in the returned plan MUST either save at least the minimum or be needed to finish. A minimum of 0 MUST return the cheapest plan unchanged. Money stays exact, with the same rounding as Feature 003.
- **FR-016**: The system MUST return 400 `same_location` when the start and finish coordinates are equal after rounding to 4 decimal places (before any routing call), and also when the routed distance or the route geometry length is below 0.01 mile (after routing, before the station search). Such a request MUST never produce a server error.

### Key Entities

- **Route plan request**: start, finish (each "City, ST" or coordinates), start fuel, corridor radius, reserve, minimum saving per stop.
- **Resolved location**: the original query and the coordinates used.
- **Route plan response**: resolved start and finish, summary, stops, map feature collection, metadata.
- **Fuel stop**: sequence, station identity and location, mile marker, distance off route, price per gallon, gallons, cost.
- **Error**: code (fixed set), message, details.
- **Cached route**: the routing result for a provider and rounded start/finish coordinates, kept for 24 hours.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A first request makes exactly 1 external routing call, and a repeated request within 24 hours makes 0; verified by automated tests with no network.
- **SC-002**: Every error case in User Story 3 returns its documented status and code in automated tests.
- **SC-003**: In every successful test response, the stop costs add up to the total fuel cost exactly, and for every stop `abs(gallons × price_usd_per_gallon − cost_usd) ≤ 0.005` (a tolerance check, not equality).
- **SC-004**: A repeated (cached) Dallas → Chicago request is answered in under 100 ms on a typical laptop, and a first request in about the routing service's response time plus under 100 ms of local work; measured by hand and recorded in the README.
- **SC-005**: One real Dallas → Chicago request works end to end locally, and the map page renders Dallas → Chicago and New York → Los Angeles with their stops (checked by hand).
- **SC-007**: With no `min_saving_per_stop_usd`, every response is the cheapest plan (identical to Feature 003, which the oracle checks). On the real Dallas → Chicago route with `min_saving_per_stop_usd = 5`, the plan has no stop that saves less than $5 unless the trip needs it, and costs at most a few dollars more than the cheapest plan (prototype: 2 stops, $0.17 more). The README documents the option, and the Postman collection includes this request.
- **SC-006**: A reviewer can run the API and the map page from a fresh clone with no API key and no frontend build.

## Assumptions

- **Building blocks.** Location resolution data comes from Feature 001's place lookup; the route and candidates from Feature 002; the plan and infeasible details from Feature 003.
- **Cache.** The route cache is the in-process cache allowed by constitution Principle VII; each server process has its own. A shared cache is future work.
- **Minimum saving per stop.** Off by default, so the default response is the provable minimum-cost plan. A client that values a driver's time can pass e.g. 5 USD (roughly 10–15 minutes of a driver's time). The rule gives fewer stops, not always the fewest: a plan with fewer stops using other stations could exist; finding it exactly needs a slower search over stations and fuel levels (future work).
- **Retry hint.** When the routing service suggests no wait, the retry hint is 30 seconds.
- **Inputs.** Coordinates are decimal degrees (latitude −90..90, longitude −180..180); "City, ST" uses US 2-letter state codes (DC included).
- **Out of scope.** Authentication and rate limiting of this API, a truck routing profile, live prices and exact station coordinates (Feature 005).
