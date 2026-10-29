# Feature Specification: Route Candidates

**Feature Branch**: `002-route-candidates`

**Created**: 2026-10-29

**Status**: Draft

**Input**: User description: "start feature 002 in new branch as i merged the first one in main". The feature content is the Feature 002 Specify input in `docs/implementation-plan.md`: "Provide the route-side building blocks of the fuel planner. Routing: given start and finish coordinates inside the USA, return the driving route as an ordered list of points plus the total distance in miles, using a free routing service that needs no API key. Exactly one external call is made per route request. The provider is selected by configuration so it can be replaced without code changes. Failures (timeout, network error, provider error, no route) surface as one well-defined 'routing unavailable' error with a readable reason, never as a hang. Requests time out after a configurable limit (default 8 seconds). Corridor search: given a route and the US fuel stations, find every station within a corridor radius of the route (default 10 miles, configurable). For each one, report its mile marker (distance along the route from the start) and its distance from the route in miles. Results are sorted by mile marker with a stable tie-break by station ID. Station data is loaded into memory once, not per request."

## Clarifications

### Session 2026-10-29

- Q: Should a station be returned if its measured distance from the route comes out slightly above the corridor radius? → A: None of the proposed options. Route samples are used only to gather candidates, with a search that is half the sample spacing wider, so no station within the radius is missed. Each candidate is then projected onto the route segments next to its nearest sample, which gives its exact distance from the route and its exact mile marker (rescaled to the provider distance). A station is included if and only if that exact distance is no more than the radius. Accuracy is 0.05 mile, and a station on the route reads 0.
- Q: When station data is rebuilt or reloaded while the app is running, how should the app pick up the new data? → A: Restart the app after rebuilding or reloading station data. There is no automatic refresh. A restart also clears the in-process route cache, which is fine. Future work: a data-version marker checked at most once per N seconds, if station data ever changes while the server runs.
- Q: When the routing service turns a request away because it is overloaded or rate-limited (HTTP 429), what should happen? → A: Raise "routing unavailable" with the reason "rate limited", with no retry (exactly 1 call). Pass on the service's suggested wait (Retry-After) as a whole number of seconds, capped at 60. If the header is missing or is a date, there is no suggested wait, and Feature 004 uses its default retry hint.

## User Scenarios & Testing *(mandatory)*

The users of this feature are the later parts of the fuel planner: the refuelling optimizer (Feature 003)
and the route-plan endpoint (Feature 004). A developer or reviewer exercises it directly through tests and
a manual check.

### User Story 1 - Get a driving route with exactly one external call (Priority: P1)

Given a start and a finish inside the USA, the planner asks a free routing service (no API key) for the
driving route. It gets back an ordered list of points that can be drawn on a map, and the total driving
distance in miles. Each route request makes exactly one call to the service. If the service is slow, down,
returns an error or finds no route, the planner gets one clear "routing unavailable" error with a readable
reason, within the configured time limit.

**Why this priority**: every later step (stations along the route, the fuel plan, the map) depends on
having the route. Keeping it to one external call is a core goal of the project.

**Independent Test**: with the routing service replaced by a recorded response (no network), request a
route between two known points. Check the request that was sent, the number of calls (1), the returned
points and the distance in miles. Then simulate a timeout, a server error and a "no route" answer.

**Acceptance Scenarios**:

1. **Given** start (32.78, -96.80) and finish (41.88, -87.63), **When** a route is requested, **Then** exactly one request is sent to the routing service. The coordinates are in the order the service requires (longitude before latitude), and the result has the route points in travel order as (latitude, longitude) plus the total distance in miles.
2. **Given** the service reports the distance in meters, **When** the route is returned, **Then** the distance is converted to miles (1 mile = 1,609.344 m).
3. **Given** the service does not answer within the time limit (default 8 seconds), **When** a route is requested, **Then** the request stops at the limit and a "routing unavailable" error is raised with the reason "timed out".
4. **Given** the service answers with a server error, an invalid response, or "no route found", **When** a route is requested, **Then** a "routing unavailable" error is raised with a readable reason, and no partial route is returned.
5. **Given** the routing provider is set by configuration, **When** an unknown provider name is configured, **Then** the planner refuses to start routing with a clear error naming the allowed providers.
6. **Given** the service answers with a server error, **When** a route is requested, **Then** exactly 1 call is made: the failure is reported, never retried.
7. **Given** the service had to move the start or the finish more than 5 miles to reach a road, **When** a route is requested, **Then** a "routing unavailable" error is raised with the reason "start/finish not near a road", and no route is returned.
8. **Given** the service rejects the request as rate-limited (HTTP 429) with a suggested wait of 2 seconds, **When** a route is requested, **Then** exactly 1 call is made and a "routing unavailable" error is raised with the reason "rate limited" and a suggested wait of 2 seconds. With no suggested wait, the error carries none. A suggested wait of 3,600 seconds is capped at 60.

---

### User Story 2 - Find the fuel stations along a route (Priority: P2)

Given a route (its points and total distance) and the shipped US station data from Feature 001, the planner
finds every station within the corridor radius of the route (default 10 miles). For each one, it reports
its mile marker (how far along the route it is from the start) and its distance from the route. The list
is sorted by mile marker, and stations at the same mile marker are ordered by station ID, so the same input
always gives the same list. Station data is loaded into memory once and reused for every route.

**Why this priority**: the optimizer can only choose among stations it is given. It depends on Story 1 for
real routes, but it can be built and tested on its own with synthetic routes.

**Independent Test**: with hand-made routes (a straight line, a two-point route with a long segment, routes
at different latitudes) and a small set of stations at known positions, check which stations are returned,
their mile markers, their off-route distances and their order. No network is needed.

**Acceptance Scenarios**:

1. **Given** a straight synthetic route and stations placed at known distances along it, **When** candidates are searched, **Then** each station's mile marker is within 0.05 mile of its true position along the route.
2. **Given** a corridor radius of 10 miles, **When** candidates are searched, **Then** a station at a true 9.99 miles from the route is included and a station at a true 10.01 miles is excluded.
3. **Given** a route made of only two points 100 miles apart, **When** candidates are searched, **Then** a station 3 miles off the middle of that segment is still found. Widely spaced route points never hide a station.
4. **Given** the same off-route distance in miles, **When** the route is in southern Texas or in northern Montana, **Then** the station is included in both cases. The radius is measured in miles at every latitude.
5. **Given** a route whose total distance comes from the routing service, **When** mile markers are computed, **Then** they use the same scale, and the end of the route is at exactly that distance.
6. **Given** two stations at the same mile marker, **When** candidates are listed, **Then** the one with the lower station ID comes first, every time.
7. **Given** the planner has already searched one route, **When** it searches a second route, **Then** the station data is not reloaded.
8. **Given** a route with no station within the radius, **When** candidates are searched, **Then** an empty list is returned (not an error).
9. **Given** no station data has been loaded (the station tables are empty or missing), **When** candidates are searched, **Then** a "station data missing" error is raised with the message "station data not loaded: run python manage.py loaddata stations". An empty list is never returned in this case.
10. **Given** a station lying exactly on the route, **When** candidates are searched, **Then** its distance from the route is 0 (within 0.01 mile).

---

### Edge Cases

- **Loops.** A route that passes near the same station twice: the station appears once, at the earliest mile marker among the route points at the minimum distance.
- **Very short routes.** A route shorter than the point spacing still gets mile markers from 0 to its total distance.
- **Station on the route.** A station exactly on the route has an off-route distance of 0 (within 0.01 mile), not the distance to the nearest route sample.
- **Radius out of range.** A radius below 1 or above 25 miles is rejected with a clear error.
- **Canadian detours.** A route that crosses into Canada (e.g. Detroit to Buffalo through Ontario) simply finds no stations on the Canadian part, because station data is US-only. Detecting the resulting gap is the optimizer's job (Feature 003).
- **Missing station data.** If the station index is empty or the station tables are missing, the search raises a clear "station data missing" error ("station data not loaded: run python manage.py loaddata stations"). It never returns an empty list for this case, so "no stations nearby" and "no data" can't be confused. Feature 004 maps this error to HTTP 503.
- **Station data changed while running.** If station data is rebuilt or reloaded while the app runs, searches keep using the data loaded at first use until the app is restarted (documented; no automatic refresh).
- **Service answers late.** An answer that arrives after the time limit is never used; the request has already failed as "timed out".

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST obtain a driving route between two coordinates from one configured routing service, with exactly one external request per route. There are no retries: a retry would be a second external call.
- **FR-002**: The default routing service MUST be free and need no API key or account.
- **FR-003**: The system MUST send coordinates in the order the service requires and MUST return route points as (latitude, longitude) in travel order.
- **FR-004**: The system MUST return the total route distance in miles, converted from the service's unit.
- **FR-005**: The routing service MUST be selected by configuration. An unknown provider name MUST produce a clear error that lists the allowed names. Only the free, no-key provider ships in this feature; others can be added later without changing the callers.
- **FR-006**: Every routing request MUST be bounded by a configurable time limit (default 8 seconds). The limit applies separately to connecting and to each read of the response, so a slow connection or a stalled answer both fail within the limit.
- **FR-007**: Timeouts, network errors, server errors, invalid responses and "no route found" MUST all surface as one "routing unavailable" error with a readable reason. No partial route is ever returned, and a failed call is reported, never repeated.
- **FR-008**: The system MUST find every US station within a corridor radius of the route. The radius is configurable from 1 to 25 miles (default 10), and is measured in miles at every latitude.
- **FR-009**: For each candidate station, the system MUST report its station ID, its mile marker (distance along the route from the start, in miles), its distance from the route (in miles) and its price per gallon (the station's exact effective price from Feature 001).
- **FR-010**: Mile markers MUST use the same scale as the route's total distance, so the end of the route is at exactly that distance.
- **FR-011**: Mile markers and off-route distances MUST be measured against the route itself, not against sampled route points. On synthetic routes they MUST be accurate to within 0.05 mile, and a station exactly on the route MUST read 0 (within 0.01 mile). A station is included if and only if its measured distance from the route is no more than the radius. No station within the radius may be missed because route points are far apart.
- **FR-012**: Candidates MUST be sorted by mile marker, then by station ID. A station near two parts of a looping route MUST appear once, at the earliest mile marker among the route points at the minimum distance.
- **FR-013**: The station data MUST be loaded into memory once, on first use, and reused for every later search, never once per request. Loading MUST NOT happen at application start-up or during project setup steps, only when a search first needs it.
  - **Contents:** the in-memory index MUST hold everything later features need without a database query: station ID, latitude, longitude, effective price (exact), name, address, city, state and coordinate source. The request path never queries the database.
  - **Reset:** tests can reset the in-memory index; production code never does.
  - **Fresh data:** after station data is rebuilt or reloaded, the app MUST be restarted to use it. There is no automatic refresh, so the request path stays free of database reads. This is documented for users.
- **FR-014**: The corridor search MUST make no external calls and MUST give the same result for the same input every time.
- **FR-015**: All routing behaviour MUST be testable without network access, using recorded service responses.
- **FR-016**: If the routing service reports that it had to move the start or the finish more than 5 miles to reach a road, the system MUST raise "routing unavailable" with the reason "start/finish not near a road". It MUST NOT return a route that starts or ends far from the requested points.
- **FR-017**: If no station data is loaded (the index is empty or the station tables are missing), the search MUST raise a "station data missing" error with the message "station data not loaded: run python manage.py loaddata stations". It MUST NOT return an empty list in this case.
- **FR-018**: If the routing service rejects a request as rate-limited (HTTP 429), the system MUST raise "routing unavailable" with the reason "rate limited" and MUST NOT retry (exactly 1 call). When the service's Retry-After value is a whole number of seconds, the error MUST carry it as the suggested wait, capped at 60 seconds. When it is missing or is a date, the error carries no suggested wait.

### Key Entities

- **Coordinate**: a latitude and longitude in decimal degrees.
- **Route**: the ordered points of the driving route, its total distance in miles, and the name of the provider that produced it.
- **Candidate station**: a station ID, its mile marker along the route (miles from the start), its distance from the route (miles) and its price per gallon (exact).
- **Station index**: the in-memory copy of the located US stations from Feature 001, built once and reused. For each station it holds the ID, latitude, longitude, effective price (exact), name, address, city, state and coordinate source, so no later step needs a database query.
- **Routing unavailable**: the single error raised for any routing failure, with a readable reason (for example "timed out", "server error", "rate limited", "no route found", "start/finish not near a road") and, when the service suggested one, a wait time in whole seconds (at most 60).
- **Station data missing**: the error raised when a search runs before station data has been loaded.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Every route request makes exactly 1 external call. The automated tests verify this with zero network access.
- **SC-002**: Every simulated timeout, error and no-route case raises "routing unavailable", and no case hangs.
- **SC-003**: On synthetic routes, every station within the radius is found and none outside it is returned (a true 9.99 miles is in, 10.01 is out). Every mile marker and off-route distance is within 0.05 mile of the true value, and a station on the route reads 0.
- **SC-004**: Searching a 3,000-mile route against about 6,600 stations takes well under 100 ms on a typical laptop. This is measured by hand and recorded in the project documentation, not asserted in automated checks.
- **SC-005**: Running the same search twice gives identical candidate lists, including order.
- **SC-006**: One manual request to the real routing service, Dallas, TX to Chicago, IL, returns a route of roughly 900–1,000 miles. The result is recorded in the project documentation.

## Assumptions

- **Station data.** Candidates come from the located stations shipped by Feature 001 (mostly city-centre coordinates, plus reviewed manual overrides). Their accuracy limits apply here too.
- **Routing service.** The default is the public demo of a free, open-source routing service with a car profile. It has no service-level agreement, so the route cache (Feature 004) and recorded test responses protect the project from its outages.
- **Detours not modelled.** The off-route distance is reported for display only. Fuel used to reach an off-route station is ignored (project assumption 6).
- **Out of scope.** Resolving "City, ST" to coordinates, the route cache and the HTTP endpoint (Feature 004); choosing stops and cost (Feature 003); a second routing provider (stretch goal).
- **Inputs.** The start and finish coordinates given to this feature are already validated as inside the USA by the caller (Feature 004).
