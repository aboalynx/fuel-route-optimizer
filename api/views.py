"""POST (and GET) /api/v1/route-plan/: parse, call the service, format, map errors."""

import logging
import re

from django.conf import settings
from rest_framework.response import Response
from rest_framework.views import APIView

from api.enums import ErrorCode
from api.exceptions import error_response
from api.presenters import present
from api.serializers import RoutePlanRequestSerializer
from api.services.route_plan import (
    InfeasibleRouteAt,
    InvalidPlanInput,
    RoutePlanInput,
    SameLocation,
    plan_route,
)
from planner.locations import LocationNotFound, LocationOutsideUS, PlaceDataMissing
from planner.optimizer import InfeasibleReason
from planner.station_index import StationDataMissing
from routing.base import RoutingUnavailable

logger = logging.getLogger(__name__)


COORDINATES = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")


class RoutePlanView(APIView):
    def post(self, request):
        return self.plan(request.data)

    def get(self, request):
        """Optional GET form: the same fields as query parameters, "lat,lng" for coordinates."""
        data = dict(request.query_params.items())
        for side in ("start", "finish"):
            match = COORDINATES.match(data.get(side, ""))
            if match:
                data[side] = {"lat": float(match[1]), "lng": float(match[2])}
        return self.plan(data)

    def plan(self, data) -> Response:
        serializer = RoutePlanRequestSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        try:
            result = plan_route(RoutePlanInput(**serializer.validated_data))
        except Exception as error:  # noqa: BLE001 - every failure becomes a JSON error body
            return error_for(error)
        return Response(present(result))


def error_for(error: Exception) -> Response:
    """The documented error response for a domain failure; anything else is internal_error."""
    match error:
        case InvalidPlanInput():
            return error_response(
                ErrorCode.INVALID_INPUT,
                error.message,
                {"field": error.field, "fields": {error.field: [error.message]}},
            )
        case LocationNotFound():
            return error_response(
                ErrorCode.LOCATION_NOT_FOUND, error.message, _location_details(error)
            )
        case LocationOutsideUS():
            return error_response(
                ErrorCode.LOCATION_OUTSIDE_US, error.message, _location_details(error)
            )
        case SameLocation():
            return error_response(
                ErrorCode.SAME_LOCATION,
                str(error),
                {"start": error.start, "finish": error.finish},
            )
        case InfeasibleRouteAt():
            return error_response(
                ErrorCode.INFEASIBLE_ROUTE, str(error.error), _gap_details(error), status=422
            )
        case RoutingUnavailable():
            retry = error.retry_after_seconds
            if retry is None:
                retry = settings.ROUTING_RETRY_AFTER_SECONDS
            return error_response(
                ErrorCode.ROUTING_UNAVAILABLE,
                f"routing unavailable: {error.reason}",
                {"reason": error.reason.value},
                status=503,
                headers={"Retry-After": str(retry)},
            )
        case StationDataMissing():
            return error_response(ErrorCode.STATION_DATA_MISSING, str(error), status=503)
        case PlaceDataMissing():
            return error_response(ErrorCode.PLACE_DATA_MISSING, str(error), status=503)
    logger.exception("route plan failed")
    return error_response(ErrorCode.INTERNAL_ERROR, "internal error", status=500)


def _location_details(error) -> dict:
    return {"field": error.field, "query": error.query}


def _gap_details(at: InfeasibleRouteAt) -> dict:
    error = at.error
    details = {
        "reason": error.reason.value,
        "gap_start_mile": error.gap_start_mile,
        "gap_end_mile": error.gap_end_mile,
        "gap_start": {"lat": at.gap_start.lat, "lng": at.gap_start.lng},
        "gap_end": {"lat": at.gap_end.lat, "lng": at.gap_end.lng},
        "usable_range_miles": error.usable_range_miles,
    }
    if error.reason == InfeasibleReason.START_FUEL_INSUFFICIENT:
        details |= {
            "start_fuel_gallons": error.start_fuel_gallons,
            "reserve_gallons": error.reserve_gallons,
            "gallons_short": error.gallons_short,
        }
    return details
