from django.conf import settings


def test_vehicle_assumptions_match_assignment():
    assert settings.VEHICLE_MAX_RANGE_MILES == 500
    assert settings.VEHICLE_MPG == 10
