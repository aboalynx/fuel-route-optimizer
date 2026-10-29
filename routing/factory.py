"""Build the configured routing provider. The only routing module that reads Django settings."""

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from routing.base import RoutingProvider
from routing.osrm import OSRMProvider

PROVIDERS = {"osrm": OSRMProvider}


def provider_from_settings() -> RoutingProvider:
    name = settings.ROUTING_PROVIDER
    if name not in PROVIDERS:
        allowed = ", ".join(sorted(PROVIDERS))
        raise ImproperlyConfigured(f"unknown ROUTING_PROVIDER {name!r}; allowed: {allowed}")
    return PROVIDERS[name](
        base_url=settings.OSRM_BASE_URL, timeout_seconds=settings.ROUTING_TIMEOUT_SECONDS
    )
