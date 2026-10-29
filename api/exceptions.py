"""One JSON error body for every failure: {"error": {"code", "message", "details"}}."""

import logging

from django.core.exceptions import PermissionDenied
from django.http import Http404
from rest_framework import exceptions
from rest_framework.response import Response
from rest_framework.views import exception_handler

from api.enums import ErrorCode

logger = logging.getLogger(__name__)


def error_response(
    code: ErrorCode,
    message: str,
    details: dict | None = None,
    status: int = 400,
    headers: dict | None = None,
) -> Response:
    body = {"error": {"code": code.value, "message": message, "details": details or {}}}
    return Response(body, status=status, headers=headers)


def error_body_exception_handler(exc, context):
    """Request errors (bad JSON, failed validation) in the same body as every other error.

    Any exception that is not one of DRF's own becomes 500 internal_error: it is logged with its
    traceback and never included in the response (even with DEBUG on).
    """
    if isinstance(exc, exceptions.ValidationError):
        return error_response(
            ErrorCode.INVALID_INPUT, _validation_message(exc.detail), {"fields": exc.detail}
        )
    if isinstance(exc, exceptions.ParseError | exceptions.UnsupportedMediaType):
        return error_response(ErrorCode.INVALID_INPUT, str(exc.detail))
    if isinstance(exc, exceptions.APIException | Http404 | PermissionDenied):
        return exception_handler(exc, context)
    logger.error("request failed", exc_info=exc)
    return error_response(ErrorCode.INTERNAL_ERROR, "internal error", status=500)


def _validation_message(detail) -> str:
    """'start: This field is required.' for the first failing field."""
    if isinstance(detail, dict) and detail:
        field, errors = next(iter(detail.items()))
        first = errors[0] if isinstance(errors, list) and errors else errors
        if isinstance(first, dict):
            return f"{field}: {_validation_message(first)}"
        return f"{field}: {first}"
    if isinstance(detail, list) and detail:
        return str(detail[0])
    return "invalid input"
