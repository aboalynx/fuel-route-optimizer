"""Response body for a planned route (contract: specs/004-route-plan-api/contracts).

Precision: money 2 dp (already rounded half up by the optimizer), gallons 4 dp, price per gallon
exact as stored, miles 3 dp. Decimals are rendered as JSON numbers.
"""

from decimal import ROUND_HALF_UP, Decimal

from api.services.route_plan import RoutePlanResult
from planner.locations import ResolvedLocation
from planner.route_output import route_geojson, thin_line

GALLONS = Decimal("0.0001")
CENTS = Decimal("0.01")


def present(result: RoutePlanResult) -> dict:
    plan = result.plan.plan
    stops = [
        {
            "sequence": n,
            "opis_id": stop.purchase.opis_id,
            "name": stop.station.name,
            "address": stop.station.address,
            "city": stop.station.city,
            "state": stop.station.state,
            "lat": stop.lat,
            "lng": stop.lng,
            "geo_source": stop.station.geo_source.value,
            "mile_marker": stop.purchase.mile_marker,
            "off_route_miles": round(stop.off_route_miles, 3),
            "price_usd_per_gallon": stop.purchase.price_usd_per_gallon,
            "gallons": gallons(stop.purchase.gallons),
            "cost_usd": stop.purchase.cost_usd,
        }
        for n, stop in enumerate(result.stops, start=1)
    ]
    vehicle = result.vehicle
    return {
        "start": location(result.start),
        "finish": location(result.finish),
        "summary": {
            "distance_miles": result.distance_miles,
            "total_gallons_consumed": gallons(plan.gallons_consumed),
            "gallons_purchased": gallons(plan.gallons_purchased),
            "fuel_left_gallons": gallons(plan.fuel_left_gallons),
            "total_fuel_cost_usd": plan.total_cost_usd,
            "stops_count": len(stops),
            "stops_dropped": result.plan.stops_dropped,
            "extra_cost_vs_cheapest_usd": result.plan.extra_cost_vs_cheapest_usd.quantize(CENTS),
            "assumptions": {
                "mpg": vehicle.mpg,
                "max_range_miles": vehicle.max_range_miles,
                "tank_capacity_gallons": vehicle.capacity_gallons,
                "start_fuel_gallons": result.start_fuel_gallons,
                "corridor_miles": result.corridor_miles,
                "reserve_gallons": result.reserve_gallons,
                "min_saving_per_stop_usd": result.min_saving_per_stop_usd,
            },
        },
        "fuel_stops": stops,
        "map": route_geojson(
            thin_line(result.route.points),
            [
                {
                    k: s[k]
                    for k in (
                        "sequence",
                        "opis_id",
                        "name",
                        "lat",
                        "lng",
                        "price_usd_per_gallon",
                        "gallons",
                        "cost_usd",
                    )
                }
                for s in stops
            ],
        ),
        "meta": {
            "routing_provider": result.route.provider,
            "routing_calls": result.routing_calls,
            "cached": result.cached,
            "candidate_stations_considered": result.candidates_count,
            "timings_ms": result.timings_ms,
        },
    }


def location(resolved: ResolvedLocation) -> dict:
    return {
        "query": resolved.query,
        "name": resolved.place_name,
        "lat": resolved.lat,
        "lng": resolved.lng,
    }


def gallons(value: Decimal) -> Decimal:
    return value.quantize(GALLONS, rounding=ROUND_HALF_UP)
