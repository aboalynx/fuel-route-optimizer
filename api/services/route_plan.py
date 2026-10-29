"""Plan a trip: resolve locations, one routing call, corridor search, optimizer.

The only place that combines the pure modules with Django (settings, the station and place
indexes). Each step is timed. See specs/004-route-plan-api/research.md.
"""

import time
from dataclasses import dataclass
from decimal import Decimal

import numpy as np
from django.conf import settings
from django.core.cache import cache

from api.services.places import get_place_index
from planner.corridor import Candidate, find_candidates
from planner.fewer_stops import FewerStopsResult, plan_with_min_saving
from planner.geometry import cumulative_miles
from planner.locations import (
    LocationError,
    PlaceIndex,
    ResolvedLocation,
    resolve_name,
    resolve_point,
)
from planner.optimizer import FuelPurchase, InfeasibleRoute, PlanStation
from planner.route_output import point_at_mile
from planner.station_index import StationIndex, StationInfo
from routing.base import LatLng, Route
from routing.cached import CachedRoutingProvider, rounded
from routing.factory import provider_from_settings
from stations.services.index_loader import get_station_index

MILE = Decimal("0.001")
MIN_ROUTE_MILES = 0.01  # shorter than this is the same location (FR-016)

Location = str | tuple[float, float]


class InvalidPlanInput(Exception):
    """A request value that cannot work with the vehicle (start fuel vs capacity and reserve)."""

    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
        super().__init__(message)


class SameLocation(Exception):
    """Start and finish are the same point (rounded) or the route is shorter than 0.01 mi."""

    def __init__(self, start: str, finish: str):
        self.start = start
        self.finish = finish
        super().__init__(f"start '{start}' and finish '{finish}' are the same location")


class InfeasibleRouteAt(Exception):
    """An InfeasibleRoute plus the coordinates of the gap's ends on the route."""

    def __init__(self, error: InfeasibleRoute, gap_start: LatLng, gap_end: LatLng):
        self.error = error
        self.gap_start = gap_start
        self.gap_end = gap_end
        super().__init__(str(error))


@dataclass(frozen=True)
class RoutePlanInput:
    start: Location
    finish: Location
    start_fuel_gallons: Decimal | None = None  # None: a full tank
    corridor_miles: Decimal = Decimal(10)
    reserve_gallons: Decimal = Decimal(0)
    min_saving_per_stop_usd: Decimal = Decimal(0)


@dataclass(frozen=True)
class Vehicle:
    mpg: Decimal
    max_range_miles: Decimal
    capacity_gallons: Decimal


@dataclass(frozen=True)
class FuelStop:
    purchase: FuelPurchase
    station: StationInfo
    lat: float
    lng: float
    off_route_miles: float


@dataclass(frozen=True)
class RoutePlanResult:
    start: ResolvedLocation
    finish: ResolvedLocation
    route: Route
    distance_miles: Decimal  # as given to the optimizer (0.001 mi)
    vehicle: Vehicle
    start_fuel_gallons: Decimal
    corridor_miles: Decimal
    reserve_gallons: Decimal
    min_saving_per_stop_usd: Decimal
    plan: FewerStopsResult
    stops: tuple[FuelStop, ...]
    routing_calls: int
    cached: bool
    candidates_count: int
    timings_ms: dict[str, int]


def vehicle_from_settings() -> Vehicle:
    mpg = Decimal(str(settings.VEHICLE_MPG))
    max_range = Decimal(str(settings.VEHICLE_MAX_RANGE_MILES))
    return Vehicle(mpg=mpg, max_range_miles=max_range, capacity_gallons=max_range / mpg)


def plan_route(inp: RoutePlanInput, *, provider=None) -> RoutePlanResult:
    timer = _Timer()

    places = get_place_index()
    start = _resolve(places, inp.start, "start")
    finish = _resolve(places, inp.finish, "finish")
    vehicle = vehicle_from_settings()
    start_fuel = _check_vehicle_inputs(inp, vehicle)
    start_point, finish_point = LatLng(start.lat, start.lng), LatLng(finish.lat, finish.lng)
    if rounded(start_point) == rounded(finish_point):  # the route-cache rounding
        raise SameLocation(start.query, finish.query)
    timer.lap("resolve")

    routes = CachedRoutingProvider(
        provider or provider_from_settings(), cache, settings.ROUTE_CACHE_TTL_SECONDS
    )
    route, cached = routes.route(start_point, finish_point)
    routing_calls = 0 if cached else 1
    if route.distance_miles < MIN_ROUTE_MILES or _geometry_miles(route) < MIN_ROUTE_MILES:
        raise SameLocation(start.query, finish.query)  # also keeps rescaling off zero
    timer.lap("routing")

    index = get_station_index()
    candidates = find_candidates(route, index, float(inp.corridor_miles))
    distance = _miles(route.distance_miles)
    stations = to_plan_stations(candidates, distance)
    timer.lap("candidates")

    try:
        result = plan_with_min_saving(
            distance,
            stations,
            min_saving_usd=inp.min_saving_per_stop_usd,
            mpg=vehicle.mpg,
            max_range_miles=vehicle.max_range_miles,
            start_fuel_gallons=start_fuel,
            reserve_gallons=inp.reserve_gallons,
        )
    except InfeasibleRoute as error:
        raise InfeasibleRouteAt(
            error,
            point_at_mile(route, float(error.gap_start_mile)),
            point_at_mile(route, float(error.gap_end_mile)),
        ) from error
    timer.lap("optimize")

    return RoutePlanResult(
        start=start,
        finish=finish,
        route=route,
        distance_miles=distance,
        vehicle=vehicle,
        start_fuel_gallons=start_fuel,
        corridor_miles=inp.corridor_miles,
        reserve_gallons=inp.reserve_gallons,
        min_saving_per_stop_usd=inp.min_saving_per_stop_usd,
        plan=result,
        stops=_fuel_stops(result.plan.purchases, index, candidates),
        routing_calls=routing_calls,
        cached=cached,
        candidates_count=len(candidates),
        timings_ms=timer.done(),
    )


def to_plan_stations(candidates: list[Candidate], distance: Decimal) -> list[PlanStation]:
    """Float mile markers -> Decimal (0.001 mi), clamped to the distance, re-sorted.

    Two markers less than 0.0005 mi apart can quantize to the same mile in the wrong ID order,
    and the optimizer rejects unsorted input, so the list is sorted again after quantizing.
    """
    stations = [
        PlanStation(c.opis_id, min(_miles(c.mile_marker), distance), c.price) for c in candidates
    ]
    return sorted(stations, key=lambda s: (s.mile_marker, s.opis_id))


def _resolve(places: PlaceIndex, location: Location, field: str) -> ResolvedLocation:
    try:
        if isinstance(location, str):
            return resolve_name(places, location)
        return resolve_point(places, *location)
    except LocationError as error:
        error.field = field
        raise


def _check_vehicle_inputs(inp: RoutePlanInput, vehicle: Vehicle) -> Decimal:
    """The start fuel to plan with; values that cannot work with the tank -> InvalidPlanInput."""
    capacity = vehicle.capacity_gallons
    start_fuel = capacity if inp.start_fuel_gallons is None else inp.start_fuel_gallons
    if start_fuel > capacity:
        raise InvalidPlanInput(
            "start_fuel_gallons",
            f"start_fuel_gallons must be at most the tank capacity ({_plain(capacity)} gal)",
        )
    if inp.reserve_gallons >= capacity:
        raise InvalidPlanInput(
            "reserve_gallons",
            f"reserve_gallons must be less than the tank capacity ({_plain(capacity)} gal)",
        )
    if start_fuel < inp.reserve_gallons:
        raise InvalidPlanInput(
            "start_fuel_gallons",
            f"start_fuel_gallons ({_plain(start_fuel)}) must be at least reserve_gallons "
            f"({_plain(inp.reserve_gallons)})",
        )
    return start_fuel


def _fuel_stops(
    purchases, index: StationIndex, candidates: list[Candidate]
) -> tuple[FuelStop, ...]:
    off_route = {c.opis_id: c.off_route_miles for c in candidates}
    stops = []
    for purchase in purchases:
        j = int(np.searchsorted(index.opis_ids, purchase.opis_id))
        stops.append(
            FuelStop(
                purchase=purchase,
                station=index.info[j],
                lat=float(index.lat[j]),
                lng=float(index.lng[j]),
                off_route_miles=float(off_route[purchase.opis_id]),
            )
        )
    return tuple(stops)


def _geometry_miles(route: Route) -> float:
    return float(cumulative_miles(np.array([(p.lat, p.lng) for p in route.points]))[-1])


def _miles(value: float) -> Decimal:
    return Decimal(float(value)).quantize(MILE)


def _plain(value: Decimal) -> str:
    return f"{value.normalize():f}"


class _Timer:
    def __init__(self):
        self.started = self.last = time.perf_counter()
        self.laps: dict[str, int] = {}

    def lap(self, name: str) -> None:
        now = time.perf_counter()
        self.laps[name] = round((now - self.last) * 1000)
        self.last = now

    def done(self) -> dict[str, int]:
        return {**self.laps, "total": round((time.perf_counter() - self.started) * 1000)}
