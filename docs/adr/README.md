# Architecture Decision Records

Each ADR records one significant decision, the alternatives considered, and the consequences. ADRs
are immutable once accepted. To change a decision, add a new ADR that supersedes the old one.

| ADR | Title | Status | Algorithm doc | Feature |
| --- | --- | --- | --- | --- |
| [0001](0001-greedy-refuelling-optimizer.md) | Greedy "next cheaper station" refuelling optimizer | Accepted | [refuelling-greedy.md](../algorithms/refuelling-greedy.md) | 003 |
| [0002](0002-kdtree-corridor-search.md) | KD-tree on 3D unit vectors for route corridor search | Accepted | [route-corridor-search.md](../algorithms/route-corridor-search.md) | 002 |
| [0003](0003-offline-centroid-geocoding.md) | Offline GeoNames city-centroid geocoding | Accepted | [station-geocoding.md](../algorithms/station-geocoding.md) | 001, 004 |
| [0004](0004-osm-fuzzy-name-matching.md) | Offline OSM matching with fuzzy names and a unique-winner rule | Accepted (stretch) | [osm-name-matching.md](../algorithms/osm-name-matching.md) | 005 |

Decisions that are not algorithms (D1 start fuel, D2 minimum price, D4 OSRM, D5–D11) are recorded in
the decisions table of the [implementation plan](../implementation-plan.md#4-decisions).

## Template

```markdown
# ADR-NNNN: <title>

- Status: Proposed | Accepted | Superseded by ADR-XXXX
- Date: YYYY-MM-DD
- Related: <algorithm doc>, <feature>, <requirements>

## Context
## Decision
## Alternatives considered
## Consequences
```
