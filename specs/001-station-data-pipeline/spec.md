# Feature Specification: Station Data Pipeline

**Feature Branch**: `001-station-data-pipeline`

**Created**: 2026-10-29

**Status**: Draft

**Input**: User description: "Build the station data set used by the route planner. Input: the provided OPIS fuel price CSV (8,151 rows; no coordinates). Keep US stations only (drop Canadian provinces). One station per OPIS Truckstop ID; keep every raw price row; the station's price is the minimum of its rows (the data gives no reason for differing prices). Every kept station needs coordinates; use the centre of its city as a baseline. Stations whose city cannot be located are reported and excluded. The result must be reproducible by a reviewer with one command, and also shipped as ready-to-load data so the project runs without any network access. Print a report: rows read, Canadian rows dropped, stations kept, stations located, stations dropped. Out of scope: precise station coordinates (a later feature), the routing API."

## Clarifications

### Session 2026-10-29

- Q: When a station is excluded because its city can't be found, should its raw price rows also be left out of the stored data set? → A: Yes. Excluded stations' price rows are excluded with them. 7,531 is the US price-row count read before exclusion, and the report also shows the stored count.
- Q: If the price file has a malformed row, should the rebuild skip it and report it, or stop with an error? → A: Stop, but only after validating the whole file first. Every problem is collected (line, column, value, reason) and reported in one error, capped at the first 50 plus a total count. Validation runs before anything is written. A missing or renamed header column fails immediately. Canadian rows are valid and are dropped silently.
- Q: If fewer than 95% of stations can be located, should the rebuild still save and export the data? → A: No, by default. A minimum located-share threshold (default 95%) can be set per run.
  - Below the threshold: print the report, write the unmatched-cities file, exit non-zero, and leave the stored data and exported files unchanged.
  - At or above the threshold: save and export as normal.
  - The report always shows the threshold next to the actual share.
  - If the shipped data is ever built with a lower threshold, the README states the value and why.
- Q: Are these speed targets right: load in under 1 minute and full rebuild in under 5 minutes on a typical laptop? → A: Yes. They are measured manually once on the developer's laptop and recorded in the README with the machine. They are not asserted in CI: the rebuild cannot run there (the gazetteer is not in the repository), and timing checks on shared runners are flaky.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Load ready-made station data offline (Priority: P1)

A reviewer clones the project and wants the route planner to have its fuel station data
immediately. They load the shipped station data with a single command, with no network access, no
account and no extra downloads. Every loaded station is in the USA, has one effective price and has
coordinates.

**Why this priority**: Every later feature (corridor search, optimizer, API) needs this data. A
reviewer who cannot get station data cannot evaluate anything else.

**Independent Test**: On a fresh checkout with the network disabled, run the single load step and
confirm the station and price records are present, with US states only, one price per station and
coordinates on every station.

**Acceptance Scenarios**:

1. **Given** a fresh checkout with no station data loaded and no network, **When** the reviewer runs the single load step, **Then** all shipped stations and their raw price rows are available, and no network request is made.
2. **Given** the loaded data, **When** any station is inspected, **Then** it has a US state, a name, an address, a city, an effective price and coordinates marked as "city centre".
3. **Given** the loaded data, **When** stations are filtered by Canadian province codes, **Then** none are found.

---

### User Story 2 - Rebuild the station data with one command (Priority: P2)

A maintainer or reviewer wants to see exactly how the shipped data was produced and to regenerate
it from the provided price file. They run one command. It cleans the price file, merges rows per
station, locates each station at its city centre using an offline place gazetteer, stores the
result, re-exports the ready-to-load data and prints a summary report.

**Why this priority**: Reproducibility makes the shipped data trustworthy and reviewable. It
matters less than having the data available (P1), because the shipped copy already lets the
project run.

**Independent Test**: Run the rebuild command twice on the provided price file and compare the
outputs. Then run it on a small sample file with known contents and compare the result with the
expected stations and prices.

**Acceptance Scenarios**:

1. **Given** the provided price file (8,151 rows), **When** the rebuild command runs, **Then** it reports 8,151 rows read, 620 Canadian rows dropped and 6,626 US stations kept before location.
2. **Given** a station ID that appears on several rows with different prices, **When** the data is rebuilt, **Then** the station has one record whose effective price is the minimum of its rows, and every raw row is kept with its original price.
3. **Given** a station ID whose rows use different name spellings, **When** the data is rebuilt, **Then** the station's display name is the first spelling seen in the file.
4. **Given** a price with 8 decimal places (e.g. 3.00733333), **When** the data is rebuilt and then loaded, **Then** the price reads back exactly, with no rounding.
5. **Given** a station whose city cannot be found in the gazetteer, **When** the data is rebuilt, **Then** that station is excluded from the data set and listed in a reviewable file of unmatched cities.
6. **Given** the rebuild has already run once, **When** it runs again on the same inputs, **Then** the stored data and the exported ready-to-load file are identical to the first run, byte for byte.
7. **Given** the rebuild finishes, **When** the maintainer reads the report, **Then** it shows rows read, Canadian rows dropped, US price rows read, price rows stored, stations kept, stations with several prices, stations located (count and percentage), stations dropped (with the path of the unmatched file), and the size of the place lookup data.
8. **Given** previously built data and a price file with two malformed rows, **When** the rebuild runs, **Then** it exits with a non-zero status and one error listing both line numbers, columns, values and reasons, and the stored data and exported files are unchanged.
9. **Given** a price file whose "Retail Price" column is missing or renamed, **When** the rebuild runs, **Then** it fails immediately with an error naming the missing column, and nothing is written.
10. **Given** previously built data and a sample whose located share is below the threshold, **When** the rebuild runs with the default threshold, **Then** it prints the report with the threshold, writes the unmatched-cities file, exits non-zero, and the stored data and exported files are unchanged. **When** the same sample is rebuilt with a threshold below its share, **Then** it saves and exports normally.

---

### User Story 3 - Ship a place lookup for later "City, ST" input (Priority: P3)

The route-planning API (a later feature) must turn input like "Dallas, TX" into coordinates without
an external call and without the large gazetteer file, which is not shipped. The rebuild command
therefore also exports a compact, shipped lookup of US populated places. It uses the same name
matching rules as the station locator.

**Why this priority**: The API needs it, but nothing in this feature uses it directly. It can be
validated on its own.

**Independent Test**: After a rebuild, look up a few known city/state pairs in the exported lookup
(e.g. Dallas, TX) and confirm they resolve to the same coordinates used for stations in those
cities.

**Acceptance Scenarios**:

1. **Given** the rebuild has run, **When** the exported place lookup is inspected, **Then** it contains every place matched by a station city plus all populated places with a known population, and its size is a few megabytes.
2. **Given** a city name written differently in the price file and the gazetteer (e.g. "ST LOUIS" vs "Saint Louis"), **When** it is looked up, **Then** both forms resolve to the same place.

---

### Edge Cases

- **Trailing spaces.** 1,256 city values in the price file have trailing spaces. Values are trimmed before any matching.
- **Abbreviated names.** City names with abbreviations or punctuation ("St.", "Ft", "Mt", "Mc Lean", hyphens, apostrophes) are normalised the same way on both sides before matching.
- **What the provided file actually contains.**
  - Its cities never abbreviate Saint/Fort/Mount; 86 city/state pairs spell them out. The expansion rules therefore mainly normalise gazetteer names such as "St. Louis".
  - 9 cities use the "Mc X" form (e.g. "Mc Lean, IL", "MC DERMITT, NV").
  - One city uses a direction abbreviation ("S Coffeyville, OK"). It is matched by the compact tier ("South Coffeyville").
- **Duplicate place names.** When several places in one state share a normalised name, the most populous one wins, and the lowest gazetteer ID breaks remaining ties.
- **Defunct places.** Historical, abandoned or destroyed places in the gazetteer are never used.
- **Alternate names.** An alternate place name is used only when no primary name matches, to avoid false matches.
- **Wrong alternate-name matches.** `Willington, CT` matches `Millington` (about 28 miles away) through an alternate name, and GeoNames has no populated place for Willington. The two Willington stations get reviewed manual coordinates from OpenStreetMap (FR-023), which win over the wrong match. The rejected-matches list (FR-022) stays available for future bad matches.
- **Spacing and punctuation differences.** "De Forest" vs GeoNames "DeForest", "Brookpark" vs "Brook Park" and "Bois D Arc" vs "Bois D'Arc" are matched by the compact tier, only when the main and alternate names both fail.
- **Exact duplicate rows.** 81 IDs have rows with the same price. They become one station, and every raw row is kept.
- **Malformed price file.** A malformed row (bad ID, bad or non-positive price, empty city/state, unknown state code) or a missing header column stops the rebuild before anything is written, with every problem listed (see FR-020).
- **Gazetteer missing.** If the gazetteer file is not present when rebuilding, the command stops with a clear message saying where to get it. The shipped data is unaffected.
- **Low match rate.** If the located share is below the minimum threshold (default 95%), the rebuild prints the report and writes the unmatched-cities file. It then exits non-zero, without changing the stored data or exported files (see FR-021).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST read the provided fuel price file and trim leading and trailing whitespace from every value.
- **FR-002**: The system MUST drop every row whose state is a Canadian province or territory code (AB, BC, MB, NB, NL, NS, NT, NU, ON, PE, QC, SK, YT).
- **FR-003**: The system MUST produce exactly one station per OPIS Truckstop ID among the remaining rows.
- **FR-004**: The system MUST keep every raw US price row of every kept station, with its rack ID, raw name and price, linked to that station. Price rows of excluded stations (FR-012) are excluded with them. No price row is ever stored without a station.
- **FR-005**: The system MUST set each station's effective price to the minimum price across its rows.
- **FR-006**: The system MUST use the first name spelling seen in the file as the station's display name, and take the station's address, city and state from its first row. (Verified on the provided file: 0 IDs have rows with a different address, city or state.)
- **FR-007**: The system MUST store prices exactly as given in the file (up to 8 decimal places), with no rounding at any stage of this feature.
- **FR-008**: The system MUST give each station the coordinates of its city centre, found by matching (city, state) against an offline gazetteer of US populated places.
- **FR-009**: The system MUST apply one name-normalisation rule to both gazetteer names and price-file cities: lower case; remove periods and apostrophes; hyphens to spaces; collapse spaces; expand st→saint, ste→sainte, ft→fort, mt→mount; join "mc x" into "mcx". For the third lookup tier (FR-010) it MUST also derive a **compact key**: the normalised name with a leading direction token expanded (n→north, s→south, e→east, w→west), then with all spaces removed (e.g. "De Forest" → "deforest", "Bois D'Arc" and "Bois D Arc" → "boisdarc", "S Coffeyville" → "southcoffeyville").
- **FR-010**: The system MUST ignore historical, abandoned and destroyed places. It MUST resolve name collisions within a state by highest population, then lowest gazetteer ID. Lookup MUST use three tiers, in this order, each within the same state: (1) main names; (2) alternate names, only when no main name matches; (3) the compact key against main names only (same tie rule), only when tiers 1 and 2 both fail. A later tier never overrides an earlier match. The tier used is recorded per station (main, alternate or compact).
- **FR-011**: The system MUST record the coordinate source of every station: "city centre" for a gazetteer match, or "manual" for a reviewed manual override (FR-023). The match score stays empty (reserved for the later precision feature).
- **FR-012**: The system MUST exclude stations whose city cannot be located, together with their price rows, and MUST write them (ID, name, city, state, reason) to a reviewable unmatched-cities file, ordered by station ID. The reason is "not found" or "rejected match: <matched name>" (FR-022). That file is committed with the shipped data, so reviewers can see every dropped station.
- **FR-013**: The system MUST replace previously built data on every rebuild rather than adding to it. Two consecutive rebuilds on the same inputs MUST produce identical stored records, including record identifiers. All three output files MUST be byte-for-byte identical between runs: the station data file, the unmatched-cities file and the place lookup.
- **FR-014**: The system MUST write each output in a fixed order:
  - the station data file (stations and their price rows, shipped and ready to load): ordered by station ID;
  - the unmatched-cities file: ordered by station ID;
  - the place lookup: ordered by state, then normalised name, and compressed with a fixed timestamp so the compressed bytes do not change between runs.
- **FR-015**: Loading the shipped data MUST need one command and no network access, and MUST NOT need the gazetteer file.
- **FR-016**: The system MUST export a compact, shipped place lookup (normalised name, display name, state, coordinates, population). It MUST cover every populated place with a known population, plus every place matched by a station city.
  - The lookup MUST have exactly one row per (normalised name, state): the winner of the FR-010 tie rule. Later "City, ST" lookups therefore resolve exactly as station matching did.
  - A place matched through an alternate name or the compact tier MUST also get a row under the station's normalised city key, unless a main name already uses that key (a main name always wins).
- **FR-017**: The rebuild MUST be a single command. It MUST accept these optional inputs:
  - the price file location (project default);
  - the gazetteer location (project default);
  - a minimum located-share threshold in percent (default 95);
  - a choice to skip the export step.
- **FR-018**: At the end of a rebuild the system MUST print a report. The report MUST show:
  - rows read;
  - Canadian rows dropped;
  - US price rows read;
  - price rows stored (after excluding unlocated stations);
  - stations kept;
  - stations with several prices;
  - stations located (count and percentage), with the threshold next to the share (e.g. "Stations located 96.8% (threshold 95%)"), and the count and share per coordinate source (city centre, manual, precise);
  - stations dropped, split into not found and rejected match (with the unmatched-file location);
  - the place lookup's size (places and megabytes).
- **FR-019**: The rebuild MUST NOT make any network request.
- **FR-020**: Before writing anything, the rebuild MUST validate the whole price file.
  - **Missing header column:** if any expected column (OPIS Truckstop ID, Truckstop Name, Address, City, State, Rack ID, Retail Price) is missing or renamed, the rebuild fails immediately.
  - **Malformed rows:** a row is malformed if:
    - the OPIS Truckstop ID or Rack ID is missing or not an integer;
    - the Retail Price is empty, not a valid decimal, zero or negative;
    - City or State is empty;
    - the State code is neither a US state/DC nor a Canadian province/territory;
    - the row shares an OPIS Truckstop ID with another row but has a different City or State. The error lists the conflicting line numbers.
  - **Error:** if any row is malformed, the rebuild MUST stop with one error and a non-zero exit status. The error lists every problem (line number, column, value, reason), capped at the first 50, plus the total count.
  - **Stored data:** after a failed validation, the stored data and the exported files MUST be exactly as they were before the run.
  - **Canadian rows:** these are valid rows, not errors. They are dropped silently and counted in the report.
- **FR-021**: The rebuild MUST compare the located share with the minimum threshold (FR-017).
  - **Below the threshold:** print the report, write the unmatched-cities file, exit with a non-zero status, and leave the stored data and exported files exactly as they were.
  - **At or above the threshold:** save and export as normal.
  - **Lower threshold:** if the shipped data is built with a threshold below the default, the project documentation MUST state the value used and the reason.
- **FR-022**: The system MUST apply a committed, reviewed rejected-matches list (`data/overrides/rejected_matches.csv`; columns city, state, matched_name, reason).
  - **Why:** a wrong location is worse than a missing one. (Willington, CT, the first case found, is now handled by a manual override, FR-023, so the shipped list may hold only its header.)
  - **Rule:** after lookup, a station whose (normalised city, state, normalised matched place name) is on the list is treated as unmatched, with reason "rejected match: <matched name>".
  - **Rejects only:** the list never supplies coordinates.
  - **Missing file:** no rejections.
  - **Validation:** the list is validated before anything is written: exact header; non-empty city, matched name and reason; a US state code; no duplicate rows. Any problem stops the rebuild with one error that lists them all (as in FR-020). A header-only file is valid.
- **FR-023**: The system MUST apply a committed, reviewed manual-coordinates list (`data/overrides/manual_coordinates.csv`; columns opis_id, lat, lng, source, note).
  - **Why:** Willington, CT (stations 52623, 71659) matched Millington through an alternate name, about 28 miles away. GeoNames has no populated place for Willington. OpenStreetMap shows both stations at I-84 Exit 71 (Ruby Rd).
  - **Rule:** after lookup, an override wins over any gazetteer match (or a missing match, or a rejected match) for that station ID. The station is located with the file's coordinates, stored exactly as written, and coordinate source "manual".
  - **Not in the place lookup:** manual stations add no place-lookup rows, so a wrong gazetteer match never leaks into "City, ST" resolution.
  - **Missing file:** no overrides.
  - **Validation:** the list is validated before anything is written, and every problem is reported with its line number. Problems are: a wrong header; an opis_id that is not an integer, is not a US station in the price file, or appears twice; lat/lng that is not a number or is outside the contiguous-US box (lat 24 to 50, lng -125 to -66); a source that is not an openstreetmap.org URL.

### Key Entities

- **Fuel station**: one physical truck stop, identified by its OPIS Truckstop ID. Attributes: display name, address, city, state, effective price (minimum of its rows), coordinates, coordinate source ("city centre", "manual" for a reviewed override, "precise" in a later feature), match score (empty for now).
- **Price row**: one raw row from the price file for a US station. Attributes: rack ID, name as written in that row, price exactly as written. Each price row belongs to exactly one station; a station has one or more price rows.
- **Place**: a US populated place from the gazetteer. Attributes: normalised name, display name, state, coordinates, population. Used to locate stations and, later, to resolve user input.
- **Rebuild report**: the summary printed at the end of a rebuild (see FR-018). It is not stored, but its numbers are copied into the project documentation.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On the provided price file, the rebuild reports 8,151 rows read, 620 Canadian rows dropped, 7,531 US price rows read and 6,626 stations kept before location. 0 Canadian stations remain. Stored price rows = 7,531 minus the rows of excluded stations, and every stored price row belongs to a stored station.
- **SC-002**: At least 95% of the 6,626 stations are located with the default threshold. Every dropped station appears in the unmatched-cities file.
- **SC-003**: Every one of the 568 stations with several price rows has an effective price equal to the minimum of its rows. A price of 3.00733333 reads back exactly after rebuild and load.
- **SC-004**: Two consecutive rebuilds produce identical record identifiers, and byte-for-byte identical copies of all three output files: station data, unmatched cities and place lookup.
- **SC-005**: A reviewer on a fresh checkout with no network access has all station data available after one load command. The load takes under 1 minute on a typical laptop.
- **SC-006**: The rebuild from the provided price file completes in under 5 minutes on a typical laptop.
- **How SC-005 and SC-006 are checked:** they are measured manually, once, on the developer's laptop. The measured times are recorded in the project documentation (e.g. "Load: 4 s. Full rebuild: 48 s"). They are not automated checks: the rebuild needs the gazetteer, which is not in the repository, and timings on shared build machines vary.
- **SC-007**: The shipped place lookup is under 10 MB, and the shipped station data is under 50 MB. Both are far below common repository file-size limits.

## Assumptions

- **Gazetteer.** The offline gazetteer is the GeoNames US file. It is downloaded once by the maintainer, is not shipped, and is needed only to rebuild. The README gives its source.
- **Minimum price rule.** The data does not explain why one station has several prices, so the minimum is used, because the station does sell at that price. Every raw row is kept, so another rule (such as the mean) could be applied later without re-reading the file.
- **Accuracy.** City-centre coordinates may be several miles from the real station. Precise coordinates are a later feature, and the route search compensates with a corridor radius.
- **Excluded stations.** Stations that cannot be located are a small share and are acceptable as long as they are listed for review.
- **Scope.** The routing API, precise station coordinates, corridor search and the optimizer are out of scope. The place lookup is produced here only because it comes from the same gazetteer pass; it is used later by the API.
- **No network.** The project's default local storage is used. No external service is contacted during rebuild or load.
