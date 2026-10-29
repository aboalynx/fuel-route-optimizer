"""T007: the provider is chosen by configuration."""

import httpx
import pytest
from django.core.exceptions import ImproperlyConfigured

from routing.factory import provider_from_settings
from routing.osrm import OSRMProvider


def test_osrm_uses_the_configured_url_and_timeout(settings):
    settings.ROUTING_PROVIDER = "osrm"
    settings.OSRM_BASE_URL = "https://osrm.example"
    settings.ROUTING_TIMEOUT_SECONDS = 5

    provider = provider_from_settings()

    assert isinstance(provider, OSRMProvider)
    assert provider.base_url == "https://osrm.example"
    assert provider.client.timeout == httpx.Timeout(5)


def test_unknown_provider_lists_the_allowed_names(settings):
    settings.ROUTING_PROVIDER = "valhalla"

    with pytest.raises(ImproperlyConfigured) as exc:
        provider_from_settings()

    assert "valhalla" in str(exc.value)
    assert "osrm" in str(exc.value)
