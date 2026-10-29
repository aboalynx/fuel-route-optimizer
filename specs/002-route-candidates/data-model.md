# Data Model: Route Candidates (002)

No new database tables. Everything here is an in-memory value type. Stored station data comes from
Feature 001 (`FuelStation`).

## Value types

### `LatLng` (`routing/base.py`, frozen dataclass)

| Field | Type | Rules |
| --- | --- | --- |
| `lat` | `float` | Degrees, −90..90 |
| `lng` | `float` | Degrees, −180..180 |

### `Route` (`routing/base.py`, frozen dataclass)

| Field | Type | Rules |
| --- | --- | --- |
| `points` | `tuple[LatLng, ...]` | Travel order, ≥ 2 points |
| `distance_miles` | `float` | Provider distance, meters / 1609.344 |
| `provider` | `str` | e.g. `"osrm"` |

**Densified route** (computed inside `find_candidates`, not stored): every original point of `points`, in order, plus linearly interpolated points so no segment is longer than `s = min(1 mi, r/2)`. It is the same polyline with extra vertices, so there is no corner-cutting on curves. Mile markers are rescaled to `distance_miles`. If `distance_miles` ÷ geometry length is outside 0.95–1.05, a warning is logged (not an error).

### `RoutingFailure` (`routing/base.py`, `StrEnum`)

`TIMED_OUT = "timed out"`, `NETWORK_ERROR = "network error"`, `SERVER_ERROR = "server error"`,
`RATE_LIMITED = "rate limited"`, `INVALID_RESPONSE = "invalid response"`,
`NO_ROUTE = "no route found"`, `NOT_NEAR_ROAD = "start/finish not near a road"`.

### `RoutingUnavailable` (`routing/base.py`, exception)

| Field | Type | Rules |
| --- | --- | --- |
| `reason` | `RoutingFailure` | Exactly one per failure |
| `detail` | `str` | Readable detail (e.g. HTTP status, provider message) |
| `retry_after_seconds` | `int \| None` | Only for `RATE_LIMITED` with an integer Retry-After; 0..60 |

### `StationIndex` (`planner/station_index.py`, frozen dataclass; pure)

Built once from the located stations of Feature 001.

| Field | Type | Notes |
| --- | --- | --- |
| `opis_ids` | `np.ndarray[int64]` | Sorted ascending |
| `lat`, `lng` | `np.ndarray[float64]` | Same order |
| `vectors` | `np.ndarray[float64]` (n, 3) | Unit vectors for the KD-tree |
| `tree` | `scipy.spatial.cKDTree` | On `vectors` |
| `info` | `tuple[StationInfo, ...]` | Same order |

`StationInfo` (frozen dataclass): `opis_id: int`, `best_price: Decimal` (exact),
`name`, `address`, `city`, `state: str`, `geo_source: GeoSource`.

**Rules:**
- An empty input raises `StationDataMissing("station data not loaded: run python manage.py loaddata stations")`.
- Equal input gives an equal index.

### `Candidate` (`planner/corridor.py`, frozen dataclass)

| Field | Type | Rules |
| --- | --- | --- |
| `opis_id` | `int` | From the index |
| `mile_marker` | `float` | Miles from the start, 0..`distance_miles`, accurate to 0.05 |
| `off_route_miles` | `float` | 0..`r`; on-route reads 0 (±0.01) |
| `price` | `Decimal` | The station's exact `best_price` |

The list returned by `find_candidates` is sorted by `(mile_marker, opis_id)`, has one entry per
station, and is empty only when the index has data but no station is within `r`.

## Lifecycle of the station index

```text
first search ─▶ get_station_index()  [stations/services/index_loader.py] (lru_cache miss)
                ├─ tables missing / empty ─▶ StationDataMissing   (not cached; next call retries)
                └─ rows ─▶ build_station_index(rows) ─▶ cached for the process lifetime
later searches ─▶ cache hit (no DB query)
station data rebuilt/reloaded ─▶ restart the process   (tests: get_station_index.cache_clear())
```

Note: `lru_cache` does not cache exceptions. After `loaddata`, the next search loads the data
without a restart. A restart is only needed when data changes after the index was built.
