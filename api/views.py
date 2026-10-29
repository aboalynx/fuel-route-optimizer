"""POST /api/v1/route-plan/: parse, call the service, format, map errors (no logic here)."""

import logging

from rest_framework.response import Response
from rest_framework.views import APIView

from api.enums import ErrorCode
from api.exceptions import error_response
from api.presenters import present
from api.serializers import RoutePlanRequestSerializer
from api.services.route_plan import InvalidPlanInput, RoutePlanInput, plan_route

logger = logging.getLogger(__name__)


class RoutePlanView(APIView):
    def post(self, request):
        serializer = RoutePlanRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = plan_route(RoutePlanInput(**serializer.validated_data))
        except Exception as error:  # noqa: BLE001 - every failure becomes a JSON error body
            return error_for(error)
        return Response(present(result))


def error_for(error: Exception) -> Response:
    """The documented error response for a domain failure; anything else is internal_error."""
    if isinstance(error, InvalidPlanInput):
        return error_response(
            ErrorCode.INVALID_INPUT,
            error.message,
            {"field": error.field, "fields": {error.field: [error.message]}},
        )
    logger.exception("route plan failed")
    return error_response(ErrorCode.INTERNAL_ERROR, "internal error", status=500)
