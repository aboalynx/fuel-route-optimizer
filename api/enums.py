"""API error codes (pure, no Django). Stored and serialized values are the plain strings."""

from enum import StrEnum


class ErrorCode(StrEnum):
    INVALID_INPUT = "invalid_input"
    LOCATION_NOT_FOUND = "location_not_found"
    LOCATION_OUTSIDE_US = "location_outside_us"
    SAME_LOCATION = "same_location"
    INFEASIBLE_ROUTE = "infeasible_route"
    ROUTING_UNAVAILABLE = "routing_unavailable"
    STATION_DATA_MISSING = "station_data_missing"
    PLACE_DATA_MISSING = "place_data_missing"
    INTERNAL_ERROR = "internal_error"
