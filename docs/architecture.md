# Architecture

Four views of the system, each derived from the code: system context, containers, the components of
the request path, and the data model. The diagrams are Mermaid, so GitHub renders them in place.

## 1. System context (C4 level 1)

```mermaid
flowchart LR
    dispatcher["Dispatcher<br/>[Person]<br/>Plans a truck trip"]
    maintainer["Maintainer<br/>[Person]<br/>Rebuilds the station data"]
    system["Fuel Route Optimizer<br/>[Software system: Django]<br/>Route-plan API and map page"]
    osrm["OSRM public demo<br/>router.project-osrm.org<br/>[External system: routing]"]
    tiles["OpenStreetMap tile servers<br/>tile.openstreetmap.org<br/>[External system: map tiles]"]
    cdn["cdnjs<br/>[External system: Leaflet 1.9.4]"]
    inputs["Price CSV + GeoNames US.txt<br/>[Input files, offline only]"]

    dispatcher -- "POST /api/v1/route-plan/<br/>or opens the map page /" --> system
    system -- "1 HTTPS GET per new route<br/>(0 when the route is cached)" --> osrm
    dispatcher -- "browser loads map tiles<br/>directly (Referer: origin)" --> tiles
    dispatcher -- "browser loads Leaflet JS/CSS<br/>(pinned, SRI)" --> cdn
    maintainer -- "python manage.py build_station_data<br/>(offline, never at request time)" --> system
    inputs -- "read by the rebuild" --> system

    classDef person fill:#08427b,stroke:#052e56,color:#ffffff
    classDef sys fill:#1168bd,stroke:#0b4884,color:#ffffff
    classDef ext fill:#999999,stroke:#6b6b6b,color:#ffffff
    class dispatcher,maintainer person
    class system sys
    class osrm,tiles,cdn,inputs ext
```

A dispatcher calls the API, or uses the map page in a browser. The only external call the system
itself makes is one OSRM routing request per new route; a repeated route makes none. Map tiles and
the Leaflet library are fetched by the browser, not by the server. Station coordinates are produced
offline by the maintainer from the price CSV and the GeoNames gazetteer.

## 2. Containers (C4 level 2)

```mermaid
flowchart TB
    browser["Browser<br/>[Map page + fetch()]"]
    client["API client<br/>[Postman, curl]"]
    maintainer["Maintainer"]

    subgraph django["Django application (one process)"]
        api["DRF API<br/>POST/GET /api/v1/route-plan/"]
        web["Map page<br/>GET / (template + Leaflet)"]
        admin["Django admin<br/>/admin/ (read-only station views)"]
        cmd["Management command<br/>build_station_data"]
        subgraph memory["In-process memory"]
            sindex["Station index + KD-tree<br/>(lru_cache, built on first use)"]
            pindex["Place index + KD-tree<br/>(lru_cache, built on first use)"]
            rcache["Route cache<br/>(LocMem, 24 h, routes only)"]
        end
    end

    db[("SQLite db.sqlite3<br/>FuelStation, FuelPrice<br/>(DATABASE_URL configurable)")]

    subgraph files["Committed data files"]
        fixture["stations/fixtures/stations.json"]
        places["data/places/us_places.csv.gz"]
        unmatched["data/reports/unmatched_cities.csv"]
        overrides["data/overrides/*.csv<br/>(manual coordinates, rejected matches)"]
    end

    osrm["OSRM public demo<br/>[External]"]
    csv["Price CSV + GeoNames US.txt"]

    client -- "JSON over HTTP" --> api
    browser -- "GET /" --> web
    browser -- "fetch() POST JSON" --> api
    api -- "read on every request<br/>(no DB query)" --> sindex
    api -- "resolve City, ST / lat,lng" --> pindex
    api -- "get / set route" --> rcache
    api -- "1 HTTPS call on a cache miss" --> osrm
    sindex -- "one SELECT per process,<br/>on first use" --> db
    pindex -- "read once on first use" --> places
    admin -- "SQL" --> db
    maintainer -- "runs" --> cmd
    csv -- "read" --> cmd
    overrides -- "read" --> cmd
    cmd -- "delete + insert in one transaction" --> db
    cmd -- "rewrites (byte-identical)" --> fixture
    cmd -- "rewrites" --> places
    cmd -- "rewrites" --> unmatched
    fixture -- "python manage.py loaddata stations<br/>(setup, never at request time)" --> db
```

Everything runs in one Django process. The request path reads only in-memory structures. The station
index is built from SQLite once per process on first use, and the place index once from the committed
gzip file. The only network call is OSRM on a route-cache miss. The rebuild command is offline. It
writes the database and the committed files in one go, and a fresh clone only needs `loaddata` to
fill SQLite from the committed fixture.

## 3. Components of the request path (C4 level 3)

```mermaid
flowchart TB
    subgraph http["HTTP layer (Django + DRF)"]
        view["api/views.py<br/>RoutePlanView: POST, GET<br/>error_for() -> status + ErrorCode"]
        ser["api/serializers.py<br/>RoutePlanRequestSerializer<br/>LocationField"]
        pres["api/presenters.py<br/>present(): precision, GeoJSON"]
        exc["api/exceptions.py<br/>error_response(), DRF handler<br/>(500 internal_error)"]
    end

    subgraph services["Services (Django)"]
        svc["api/services/route_plan.py<br/>plan_route(): resolve, same-location checks,<br/>route, corridor, optimize, timings"]
        places["api/services/places.py<br/>get_place_index()"]
        loader["stations/services/index_loader.py<br/>get_station_index()"]
        factory["routing/factory.py<br/>provider_from_settings()"]
    end

    subgraph pure["Pure modules (no Django)"]
        loc["planner/locations.py<br/>resolve_name, resolve_point"]
        cached["routing/cached.py<br/>CachedRoutingProvider"]
        osrmp["routing/osrm.py<br/>OSRMProvider"]
        base["routing/base.py<br/>LatLng, Route, RoutingUnavailable"]
        corr["planner/corridor.py<br/>find_candidates"]
        geo["planner/geometry.py<br/>densify, unit vectors, projection"]
        sidx["planner/station_index.py<br/>build_station_index (cKDTree)"]
        fewer["planner/fewer_stops.py<br/>plan_with_min_saving"]
        opt["planner/optimizer.py<br/>plan_refuelling (Decimal)"]
        out["planner/route_output.py<br/>thin_line, point_at_mile, route_geojson"]
    end

    model[("stations.models.FuelStation")]
    osrm["OSRM [External]"]

    view --> ser
    view --> svc
    view --> pres
    view -. "unexpected errors" .-> exc
    svc --> places --> loc
    svc --> cached
    cached --> factory --> osrmp
    osrmp -- "1 HTTPS GET" --> osrm
    osrmp --- base
    svc --> loader --> sidx
    loader -- "once per process" --> model
    svc --> corr --> geo
    corr --> sidx
    svc --> fewer --> opt
    svc -- "gap coordinates (422)" --> out
    pres --> out

    classDef pureStyle fill:#e6f4ea,stroke:#2e7d32,color:#1b3d1f
    classDef djangoStyle fill:#e8eefc,stroke:#1f4fb2,color:#16285a
    class loc,cached,osrmp,base,corr,geo,sidx,fewer,opt,out pureStyle
    class view,ser,pres,exc,svc,places,loader,factory djangoStyle
```

**Legend:** green boxes are pure Python modules with no Django import (checked by AST tests), and
blue boxes use Django. The offline pipeline modules `stations/pipeline/*` are pure too, but they are
not on the request path.

The view parses the input and calls one service, `plan_route`. The service resolves both locations
against the in-memory place index, rejects identical points, and gets the route from the cache or
from one OSRM call. It then finds the stations in the corridor and runs the optimizer with the
minimum-saving rule. Everything that decides a result is in the green pure modules; the blue layer
only wires them to settings, the cache and the database.

## 4. Data model (ERD)

```mermaid
erDiagram
    FUEL_STATION ||--|{ FUEL_PRICE : "prices (on_delete CASCADE)"
    FUEL_STATION {
        IntegerField opis_id PK "OPIS Truckstop ID"
        CharField name "max_length 120"
        CharField address "max_length 200"
        CharField city "max_length 80"
        CharField state "max_length 2, indexed"
        FloatField lat "null"
        FloatField lng "null"
        CharField geo_source "max_length 20; city_centroid, manual, osm (reserved)"
        PositiveSmallIntegerField match_score "null; always null today"
        DecimalField best_price "max_digits 12, decimal_places 8; minimum of the station's prices"
    }
    FUEL_PRICE {
        BigAutoField id PK "assigned 1..N by the rebuild"
        IntegerField station_id FK "-> FuelStation.opis_id"
        IntegerField rack_id
        CharField raw_name "max_length 120"
        DecimalField price "max_digits 12, decimal_places 8"
    }
```

Two tables, from `stations/models/fuel_station.py` and `stations/models/fuel_price.py`. Each US
station appears once, keyed by its OPIS ID, with every raw price row kept in `FuelPrice`. The rebuild
only creates stations that have at least one price row, so the relation is one to one-or-more.

**Not tables:** the place lookup used for `"City, ST"` input is a committed gzip file
(`data/places/us_places.csv.gz`), loaded into memory once. The request path never queries the
database after the station index is built: one `SELECT` of `FuelStation` per process, on the first
request. `FuelPrice` is never read at request time; it is kept for traceability and the admin.
