# Feature Specification: OSM Precision Layer

**Feature Branch**: `005-osm-precision-layer`

**Created**: 2026-10-30

**Status**: Draft

**Input**: User description: "merge and push and start specs for next feature". The feature content is the Feature 005 Specify input in `docs/implementation-plan.md`: "Extend the offline station-data pipeline with an optional precision step. For each US state, fetch all fuel stations from OpenStreetMap once and cache them on disk, so re-runs make no network calls. For each priced station, consider OpenStreetMap stations near its city and match by cleaned name/brand similarity. Accept a match only when the score is at least 85 and there is a single clear winner; otherwise keep the city coordinates. An OpenStreetMap station is assigned to at most one priced station, by a fixed rule. Record the coordinate source and match score per station. The report adds precise / city-centroid / dropped percentages. The step can be skipped with a flag, and the project works fully without it. Acceptance: re-running uses only the disk cache; tied candidates never move a station; below-threshold candidates are rejected; the regenerated data file is committed with updated README numbers."

## User Scenarios & Testing *(mandatory)*

The users are the maintainer who rebuilds the shipped station data, and indirectly every API user:
stations located at their real position instead of their city centre give truer "distance off
route" values and markers on the map. A reviewer checks the result through the build report and the
README numbers.

### User Story 1 - Rebuild station data with precise locations (Priority: P1) 🎯 MVP

The maintainer runs the station-data build. For each US state it gets all fuel stations from
OpenStreetMap (once; later builds reuse what was saved), matches each priced station to an
OpenStreetMap station near its city by name, and stores the exact position for confident matches.
The build report says how many stations are now precise, how many keep their city centre, and how
many were dropped.

**Why this priority**: today every station sits at its city centre, which can be miles from the
real pumps; "distance off route" and the map markers are only approximate. This is the feature's
whole value.

**Independent Test**: with saved OpenStreetMap samples for a few states and a small price file (no
network), run the build and check which stations moved, their new coordinates, their recorded
source and score, and the report percentages.

**Acceptance Scenarios**:

1. **Given** a priced station "PILOT TRAVEL CENTER #1243" in Gila Bend, AZ and an OpenStreetMap fuel station branded "Pilot Flying J" 2 miles from the Gila Bend centre, **When** the build runs, **Then** the station takes the OpenStreetMap position, its coordinate source is "OpenStreetMap" and its match score (0–100) is recorded.
2. **Given** an OpenStreetMap station mapped as an area (a forecourt outline) rather than a point, **When** it is a match, **Then** the station takes the area's centre.
3. **Given** a finished build, **When** the report is printed, **Then** it shows the count and percentage of stations located precisely, at their city centre, by manual override, and dropped, and these add up to all stations kept.
4. **Given** the new data, **When** it is committed, **Then** the README shows the new percentages and the API needs no change to use it.

---

### User Story 2 - Never move a station on weak evidence (Priority: P1)

A wrong position is worse than an honest city centre. A station only moves when exactly one
OpenStreetMap station near its city matches its name strongly; anything doubtful keeps the city
centre.

**Why this priority**: same priority as Story 1, because a precise-looking but wrong location
would mislead the driver more than the current approximation.

**Independent Test**: with hand-made samples covering each doubtful case, check that the station
keeps its city centre and records no OpenStreetMap score.

**Acceptance Scenarios**:

1. **Given** the best candidate scores below 85, **When** the build runs, **Then** the station keeps its city centre.
2. **Given** two candidates tie for the best score (for example two "Shell" stations in the same town), **When** the build runs, **Then** the station keeps its city centre.
3. **Given** the only good candidate is more than 15 miles from the city centre, **When** the build runs, **Then** it is not considered and the station keeps its city centre.
4. **Given** two priced stations both match the same OpenStreetMap station, **When** the build runs, **Then** the one with the higher score takes it, on equal scores the lower station ID takes it, and the other keeps its city centre.
5. **Given** a station with a reviewed manual coordinate override, **When** the build runs, **Then** the manual coordinates are kept, whatever OpenStreetMap says.
6. **Given** the same inputs and the same saved OpenStreetMap data, **When** the build runs twice, **Then** the results are identical.

---

### User Story 3 - Rebuild offline, or skip the step (Priority: P2)

Once the OpenStreetMap data has been saved, rebuilding needs no network. The step can also be
skipped entirely, and the project (tests, API, map) works fully without it.

**Why this priority**: the shared OpenStreetMap service is volunteer-run and rate-limited, and
reviewers must be able to run everything without it (constitution VIII).

**Independent Test**: run the build twice with saved data and confirm no network request is made
the second time; run it with the skip option and confirm the result equals today's city-centre
build.

**Acceptance Scenarios**:

1. **Given** OpenStreetMap data saved for every state, **When** the build runs again, **Then** it makes no network request.
2. **Given** the skip option, **When** the build runs, **Then** no OpenStreetMap data is read or fetched and every station keeps its city-centre or manual location, exactly as before this feature.
3. **Given** the OpenStreetMap service fails or times out for one state, **When** the build runs, **Then** that state's stations keep their city centres, the report names the state, nothing partial is saved for it, and the next run tries that state again.
4. **Given** OpenStreetMap data is fetched, **When** the build runs, **Then** it asks for one state at a time with a pause between requests, as the service's usage policy asks.
5. **Given** a fresh clone, **When** a reviewer follows the README setup, **Then** everything works without fetching OpenStreetMap data, because the built station data is committed.

---

### Edge Cases

- **Dropped stations.** Stations whose city is not found stay dropped; with no city centre there is no "near the city" to search, and this feature does not try to rescue them.
- **Missing names.** OpenStreetMap stations without a name or brand cannot match by name and are ignored.
- **Generic names.** Store numbers ("#1243") and generic words ("travel center", "truck stop", "dba") are ignored when comparing names, so "PILOT TRAVEL CENTER #1243" compares as "pilot".
- **Brand vs name.** The better of the OpenStreetMap name and brand is used, since the brand is often the cleaner of the two.
- **Several pumps under one name.** Two candidates with the same top score are a tie: the station does not move.
- **Stale OpenStreetMap data.** The saved data is a snapshot; the report states when each state was fetched. Refreshing means deleting the saved data and rebuilding.
- **Licence.** OpenStreetMap data is under the ODbL; the README credits it (already present for the two manual overrides) and states that station coordinates may now come from OpenStreetMap.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The station-data build MUST include an optional precision step that, for each US state (50 states and DC), obtains all OpenStreetMap fuel stations (points and areas, using an area's centre) with their name and brand.
- **FR-002**: OpenStreetMap data MUST be fetched at most once per state and saved on disk; a later build MUST use the saved data and make no network request for that state. Requests MUST go one state at a time with a pause between them, and each MUST time out rather than hang.
- **FR-003**: If fetching a state fails, the build MUST keep that state's stations at their current locations, save nothing for that state, report the failure by state, and still finish the rest.
- **FR-004**: For each priced station that has a city centre, the candidates MUST be the OpenStreetMap stations within 15 miles of that centre.
- **FR-005**: Names MUST be compared after cleaning (lower case, store numbers and the generic words "travel center(s)", "travel plaza", "truck stop" and "dba" removed, extra spaces collapsed). A candidate's score MUST be the higher of its name similarity and its brand similarity, on a 0–100 scale that ignores word order and extra words.
- **FR-006**: A station MUST move to a candidate only if that candidate's score is at least 85 and no other candidate has the same top score. Otherwise it MUST keep its current location.
- **FR-007**: An OpenStreetMap station MUST be assigned to at most one priced station: the higher score wins, on equal scores the lower station ID wins, and the other station keeps its location.
- **FR-008**: Reviewed manual coordinate overrides MUST take precedence over OpenStreetMap matches.
- **FR-009**: For every moved station the build MUST record the coordinate source "OpenStreetMap" and the match score; other stations keep their source (city centre or manual) and no OpenStreetMap score.
- **FR-010**: The build report MUST show the count and percentage of stations located by OpenStreetMap, by city centre, by manual override, and dropped, and the OpenStreetMap fetch date per state (or a summary of the date range).
- **FR-011**: A skip option MUST run the build without reading or fetching any OpenStreetMap data, producing exactly today's result.
- **FR-012**: The build MUST be deterministic: the same price file, gazetteer, overrides and saved OpenStreetMap data give byte-identical output files.
- **FR-013**: The regenerated station data MUST be committed, and the README MUST show the new percentages and the OpenStreetMap attribution.
- **FR-014**: All behaviour MUST be testable without network access, using saved OpenStreetMap samples.
- **FR-015**: A rebuild from a fresh clone [NEEDS CLARIFICATION: should a reviewer be able to reproduce the committed, OpenStreetMap-precise station data byte for byte without fetching from OpenStreetMap? Option A: commit a compact snapshot of the OpenStreetMap fuel stations (about a few MB compressed) that the build reads; Option B: commit nothing extra, so a rebuild without saved OpenStreetMap data gives city-centre results that differ from the committed file (documented); Option C: commit the full raw saved responses (tens of MB)].

### Key Entities

- **OpenStreetMap fuel station**: an OpenStreetMap ID, its position (a point, or an area's centre), name and brand, and the state it was fetched for.
- **Saved state data**: the OpenStreetMap fuel stations of one state as fetched once, with the fetch date.
- **Match**: a priced station, its chosen OpenStreetMap station, and the score; or "no match" with the reason (below threshold, tie, no candidate, lost to a higher score, manual override).
- **Station (existing)**: gains no new fields; its coordinates, coordinate source and match score are updated for matched stations.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A second build with saved OpenStreetMap data makes 0 network requests (verified by tests with no network).
- **SC-002**: In tests, every tie, below-threshold, out-of-radius, lost-conflict and manual-override case keeps the station's previous location.
- **SC-003**: On the real data, a review of 25 randomly chosen (fixed seed) accepted matches finds at least 24 correct (the station and the OpenStreetMap point are the same business); the result is recorded in the README.
- **SC-004**: The report's OpenStreetMap / city centre / manual / dropped counts add up to the stations kept, and the README shows the same percentages as the committed data.
- **SC-005**: With the skip option, the build output is byte-identical to today's committed data.
- **SC-006**: Every existing test (API, corridor, optimizer, pipeline) still passes with the new data; the API needs no code change.

## Assumptions

- **Optional and offline.** OpenStreetMap is used only while building station data, never while answering a request (constitution II). The request path is unchanged.
- **Service etiquette.** The public OpenStreetMap query service is volunteer-run and rate-limited; one request per state, sequential, with a pause, and a generous timeout per state (large states take long).
- **Precision over recall.** Many stations will keep their city centre; that is accepted, and the percentages are shown honestly.
- **Thresholds.** 85 and 15 miles are judgement calls from the design (ADR-0004); the report shows their effect, and changing them is a code change, not a setting.
- **Saved data location.** Saved OpenStreetMap responses live in a git-ignored folder (`data/cache/`), like the gazetteer download.
- **Out of scope.** Rescuing dropped stations, matching by address, refreshing OpenStreetMap data automatically, and any change to the API or map page.
- **Priority.** This is the implementation plan's stretch feature; it ships only if time allows after the Release step (README, Postman, coverage, Loom).
