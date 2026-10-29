"""T017: the build_station_data command end to end, on the sample files."""

import csv
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from stations.enums import GeoSource
from stations.models import FuelPrice, FuelStation

pytestmark = pytest.mark.django_db


@pytest.fixture
def run(fixtures_dir, out_dirs):
    """Run the command on the samples, writing outputs only to tmp_path."""

    def _run(**overrides):
        options = {
            "csv": fixtures_dir / "sample_fuel.csv",
            "geonames": fixtures_dir / "sample_geonames.txt",
            "min_geocoded_pct": 50,
            "fixture_out": out_dirs.fixture,
            "unmatched_out": out_dirs.unmatched,
            "places_out": out_dirs.places,
            "stdout": StringIO(),
        } | overrides
        call_command("build_station_data", **options)
        return options["stdout"].getvalue()

    return _run


def snapshot(out_dirs):
    return (
        list(FuelStation.objects.order_by("pk").values_list("pk", "best_price", "city")),
        list(FuelPrice.objects.order_by("pk").values_list("pk", "station_id", "price")),
        out_dirs.fixture.read_bytes() if out_dirs.fixture.exists() else None,
    )


# (a) happy path
def test_happy_path_stores_stations_and_prints_the_report(run, out_dirs):
    stdout = run()

    assert FuelStation.objects.count() == 12
    assert FuelPrice.objects.count() == 16
    st_louis = FuelStation.objects.get(pk=101)
    assert st_louis.best_price == Decimal("3.00733333")
    assert (st_louis.city, st_louis.lat, st_louis.lng) == ("St. Louis", 38.62727, -90.19789)
    assert set(FuelStation.objects.values_list("geo_source", flat=True)) == {
        GeoSource.CITY_CENTROID
    }
    assert not FuelStation.objects.exclude(match_score=None).exists()
    assert not FuelStation.objects.filter(pk=106).exists()

    assert "Rows read 19 | Canadian rows dropped 2 | US price rows read 17" in stdout
    assert "Stations located 12 (92.3%, threshold 50%)" in stdout

    with open(out_dirs.unmatched, newline="", encoding="utf-8") as f:
        assert list(csv.reader(f)) == [
            ["opis_id", "name", "city", "state"],
            ["106", "GHOST GAS", "Nowhereville", "KS"],
        ]
    assert out_dirs.fixture.exists()


# (b) idempotence
def test_two_runs_give_identical_keys_and_bytes(run, out_dirs):
    run()
    first = snapshot(out_dirs) + (out_dirs.unmatched.read_bytes(),)
    run()
    second = snapshot(out_dirs) + (out_dirs.unmatched.read_bytes(),)

    assert first == second
    assert [pk for pk, *_ in first[1]] == list(range(1, 17))


# (c) precision survives the fixture round trip
def test_eight_decimal_price_survives_fixture_round_trip(run, out_dirs):
    run()
    FuelPrice.objects.all().delete()
    FuelStation.objects.all().delete()

    call_command("loaddata", out_dirs.fixture, verbosity=0)

    assert FuelStation.objects.get(pk=101).best_price == Decimal("3.00733333")
    assert FuelPrice.objects.filter(price=Decimal("3.00733333")).count() == 1


# (d) malformed rows: nothing changes
def test_bad_rows_fail_and_change_nothing(run, out_dirs, fixtures_dir):
    run()
    before = snapshot(out_dirs) + (out_dirs.unmatched.read_bytes(),)

    with pytest.raises(CommandError) as exc:
        run(csv=fixtures_dir / "sample_fuel_bad.csv")

    assert "line 3, Retail Price" in str(exc.value)
    assert "line 5, City" in str(exc.value)
    assert snapshot(out_dirs) + (out_dirs.unmatched.read_bytes(),) == before


# (e) renamed header: fails before anything is written
def test_renamed_header_fails_immediately(run, out_dirs, tmp_path, fixtures_dir):
    text = (fixtures_dir / "sample_fuel.csv").read_text(encoding="utf-8")
    renamed = tmp_path / "renamed.csv"
    renamed.write_text(text.replace("Retail Price", "Price", 1), encoding="utf-8")

    with pytest.raises(CommandError, match="missing or renamed column: Retail Price"):
        run(csv=renamed)

    assert FuelStation.objects.count() == 0
    assert not out_dirs.fixture.exists()
    assert not out_dirs.unmatched.exists()


# (f) below the threshold: only the report and the unmatched file
def test_below_threshold_keeps_data_and_fixture(run, out_dirs):
    run()
    before = snapshot(out_dirs)
    out_dirs.unmatched.unlink()
    stdout = StringIO()

    with pytest.raises(CommandError, match="below"):
        run(min_geocoded_pct=95, stdout=stdout)

    assert "Stations located 12 (92.3%, threshold 95%)" in stdout.getvalue()
    assert out_dirs.unmatched.exists()
    assert snapshot(out_dirs) == before


def test_lower_threshold_passes(run):
    run(min_geocoded_pct=92)

    assert FuelStation.objects.count() == 12


def test_threshold_must_be_a_percentage(run):
    with pytest.raises(CommandError):
        run(min_geocoded_pct=101)


# (g) missing gazetteer
def test_missing_gazetteer_names_path_and_url(run, out_dirs, tmp_path):
    missing = tmp_path / "US.txt"

    with pytest.raises(CommandError) as exc:
        run(geonames=missing)

    assert str(missing) in str(exc.value)
    assert "https://download.geonames.org/export/dump/US.zip" in str(exc.value)
    assert FuelStation.objects.count() == 0
    assert not out_dirs.unmatched.exists()


# (h) --no-export
def test_no_export_stores_but_writes_no_fixture(run, out_dirs):
    run(no_export=True)

    assert FuelStation.objects.count() == 12
    assert not out_dirs.fixture.exists()


# (i) --skip-osm is accepted and changes nothing
def test_skip_osm_is_a_no_op(run, out_dirs):
    run()
    before = snapshot(out_dirs)

    run(skip_osm=True)

    assert snapshot(out_dirs) == before
