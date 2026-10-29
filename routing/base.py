"""Routing value types and the provider interface (pure, no Django)."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


@dataclass(frozen=True)
class LatLng:
    lat: float
    lng: float


@dataclass(frozen=True)
class Route:
    points: tuple[LatLng, ...]  # travel order, at least 2
    distance_miles: float  # the provider's driving distance
    provider: str


class RoutingFailure(StrEnum):
    """Why a route could not be obtained; every failure maps to exactly one of these."""

    TIMED_OUT = "timed out"
    NETWORK_ERROR = "network error"
    SERVER_ERROR = "server error"
    RATE_LIMITED = "rate limited"
    INVALID_RESPONSE = "invalid response"
    NO_ROUTE = "no route found"
    NOT_NEAR_ROAD = "start/finish not near a road"


class RoutingUnavailable(Exception):
    """The single error raised for any routing failure. Routing calls are never retried."""

    def __init__(self, reason: RoutingFailure, detail: str, retry_after_seconds: int | None = None):
        self.reason = reason
        self.detail = detail
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"routing unavailable: {reason}: {detail}")


class RoutingProvider(Protocol):
    name: str

    def route(self, start: LatLng, finish: LatLng) -> Route:
        """Return the driving route with exactly one external call."""
        ...
