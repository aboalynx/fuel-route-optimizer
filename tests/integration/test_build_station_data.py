"""T017: the build_station_data command end to end, on the sample files."""

import csv
import gzip
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
            "rejected_matches": out_dirs.fixture.parent / "no_rejections.csv",
            "manual_coordinates": out_dirs.fixture.parent / "no_overrides.csv",
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

    assert FuelStation.objects.count() == 14
    assert FuelPrice.objects.count() == 18
    st_louis = FuelStation.objects.get(pk=101)
    assert st_louis.best_price == Decimal("3.00733333")
    assert (st_louis.city, st_louis.lat, st_louis.lng) == ("St. Louis", 38.62727, -90.19789)
    assert set(FuelStation.objects.values_list("geo_source", flat=True)) == {
        GeoSource.CITY_CENTROID
    }
    assert not FuelStation.objects.exclude(match_score=None).exists()
    assert not FuelStation.objects.filter(pk=106).exists()

    assert "Rows read 21 | Canadian rows dropped 2 | US price rows read 19" in stdout
    assert "Stations located 14 (93.3%, threshold 50%)" in stdout
    assert FuelStation.objects.get(pk=114).city == "De Forest"  # located by the compact tier

    with open(out_dirs.unmatched, newline="", encoding="utf-8") as f:
        assert list(csv.reader(f)) == [
            ["opis_id", "name", "city", "state", "reason"],
            ["106", "GHOST GAS", "Nowhereville", "KS", "not found"],
        ]
    assert out_dirs.fixture.exists()


# (b) idempotence
def test_two_runs_give_identical_keys_and_bytes(run, out_dirs):
    run()
    first = snapshot(out_dirs) + (out_dirs.unmatched.read_bytes(),)
    run()
    second = snapshot(out_dirs) + (out_dirs.unmatched.read_bytes(),)

    assert first == second
    assert [pk for pk, *_ in first[1]] == list(range(1, 19))


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

    assert "Stations located 14 (93.3%, threshold 95%)" in stdout.getvalue()
    assert out_dirs.unmatched.exists()
    assert snapshot(out_dirs) == before


def test_lower_threshold_passes(run):
    run(min_geocoded_pct=93)

    assert FuelStation.objects.count() == 14


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

    assert FuelStation.objects.count() == 14
    assert not out_dirs.fixture.exists()


# --- place lookup (US3, T026) ---------------------------------------------------------------


def place_lookup_rows(path):
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        return list(csv.reader(f))


def test_happy_path_writes_the_place_lookup(run, out_dirs):
    stdout = run()

    rows = place_lookup_rows(out_dirs.places)
    assert rows[0] == ["normalised_name", "display_name", "state", "lat", "lng", "population"]
    assert ["saint louis", "Saint Louis", "MO", "38.62727", "-90.19789", "301578"] in rows
    assert len(rows) == 1 + 12
    assert "Places index 12 places, 0.0 MB" in stdout


def test_place_lookup_bytes_are_identical_across_runs(run, out_dirs):
    run()
    first = out_dirs.places.read_bytes()
    run()

    assert out_dirs.places.read_bytes() == first


def test_no_export_writes_no_place_lookup(run, out_dirs):
    stdout = run(no_export=True)

    assert not out_dirs.places.exists()
    assert "Places index" not in stdout


def test_failures_leave_the_place_lookup_unchanged(run, out_dirs, fixtures_dir):
    run()
    before = out_dirs.places.read_bytes()

    with pytest.raises(CommandError):
        run(csv=fixtures_dir / "sample_fuel_bad.csv")
    with pytest.raises(CommandError):
        run(min_geocoded_pct=95)

    assert out_dirs.places.read_bytes() == before


# --- rejected-matches list (FR-022) ---------------------------------------------------------


def test_rejected_match_is_dropped_with_its_reason(run, out_dirs, fixtures_dir):
    stdout = run(rejected_matches=fixtures_dir / "sample_rejected_matches.csv")

    assert not FuelStation.objects.filter(pk=105).exists()
    assert FuelStation.objects.count() == 13
    assert "Stations dropped 2 (not found 1, rejected match 1)" in stdout
    with open(out_dirs.unmatched, newline="", encoding="utf-8") as f:
        assert list(csv.reader(f))[1:] == [
            ["105", "HOMETOWN FUEL", "Hometown", "KS", "rejected match: New Hometown"],
            ["106", "GHOST GAS", "Nowhereville", "KS", "not found"],
        ]


def test_malformed_rejected_matches_file_changes_nothing(run, out_dirs, tmp_path):
    run()
    before = snapshot(out_dirs) + (out_dirs.unmatched.read_bytes(), out_dirs.places.read_bytes())
    bad = tmp_path / "bad_rejected.csv"
    bad.write_text("city,state,matched_name,reason\nHometown,ZZ,New Hometown,x\n", encoding="utf-8")

    with pytest.raises(CommandError, match="line 2, state, 'ZZ': unknown state code"):
        run(rejected_matches=bad)

    after = snapshot(out_dirs) + (out_dirs.unmatched.read_bytes(), out_dirs.places.read_bytes())
    assert after == before


# --- manual coordinates (FR-023) ------------------------------------------------------------


def test_manual_override_is_stored_as_manual(run, fixtures_dir):
    stdout = run(manual_coordinates=fixtures_dir / "sample_manual_coordinates.csv")

    station = FuelStation.objects.get(pk=105)
    assert (station.geo_source, station.lat, station.lng) == (GeoSource.MANUAL, 38.94, -97.15)
    assert "manual 1 (7.14%)" in stdout


@pytest.mark.parametrize(
    "row",
    [
        "999999,38.9,-97.1,https://www.openstreetmap.org/node/1,unknown id",
        "105,60.0,-97.1,https://www.openstreetmap.org/node/1,outside the box",
        "105,38.9,-97.1,https://example.com/x,not osm",
    ],
)
def test_invalid_manual_file_changes_nothing(run, out_dirs, tmp_path, row):
    run()
    before = snapshot(out_dirs) + (out_dirs.unmatched.read_bytes(), out_dirs.places.read_bytes())
    bad = tmp_path / "bad_manual.csv"
    bad.write_text(f"opis_id,lat,lng,source,note\n{row}\n", encoding="utf-8")

    with pytest.raises(CommandError, match="line 2"):
        run(manual_coordinates=bad)

    after = snapshot(out_dirs) + (out_dirs.unmatched.read_bytes(), out_dirs.places.read_bytes())
    assert after == before
