"""Request validation for the route-plan endpoint. Numbers are parsed straight to Decimal."""

from decimal import Decimal

from django.conf import settings
from rest_framework import serializers

MAX_QUERY_LENGTH = 100


class LocationField(serializers.Field):
    """A "City, ST" string, or {"lat": .., "lng": ..} -> a (lat, lng) float pair."""

    default_error_messages = {
        # DRF formats these with str.format, so literal braces are doubled.
        "invalid": 'expected "City, ST" or {{"lat": <number>, "lng": <number>}}',
        "blank": "must not be blank",
        "too_long": f"must be at most {MAX_QUERY_LENGTH} characters",
        "range": "lat must be -90..90 and lng -180..180",
    }

    def to_internal_value(self, data):
        if isinstance(data, str):
            text = data.strip()
            if not text:
                self.fail("blank")
            if len(text) > MAX_QUERY_LENGTH:
                self.fail("too_long")
            return text
        if isinstance(data, dict) and set(data) == {"lat", "lng"}:
            lat, lng = data["lat"], data["lng"]
            if not all(isinstance(v, int | float) and not isinstance(v, bool) for v in (lat, lng)):
                self.fail("invalid")
            if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                self.fail("range")
            return (float(lat), float(lng))
        self.fail("invalid")

    def to_representation(self, value):
        return value


def _decimal(max_value, decimal_places=4, min_value=0, **kwargs):
    return serializers.DecimalField(
        max_digits=10,
        decimal_places=decimal_places,
        min_value=Decimal(min_value),
        max_value=Decimal(max_value) if max_value is not None else None,
        required=False,
        **kwargs,
    )


class RoutePlanRequestSerializer(serializers.Serializer):
    start = LocationField()
    finish = LocationField()
    # The tank capacity check (start fuel <= capacity) needs the vehicle: the service does it.
    start_fuel_gallons = _decimal(max_value=None, default=None, allow_null=True)
    corridor_miles = _decimal(max_value=25, decimal_places=3, min_value=1)
    reserve_gallons = _decimal(max_value=25, default=Decimal(0))
    min_saving_per_stop_usd = _decimal(max_value=100, decimal_places=2, default=Decimal(0))

    def validate(self, attrs):
        unknown = sorted(set(self.initial_data) - set(self.fields))
        if unknown:
            raise serializers.ValidationError({name: ["unknown field"] for name in unknown})
        attrs.setdefault("corridor_miles", Decimal(str(settings.CORRIDOR_MILES)))
        return attrs
