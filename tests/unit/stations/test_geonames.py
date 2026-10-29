"""T014: place-name normalisation and the offline gazetteer (pure, no DB)."""

import pytest

from stations.enums import MatchVia
from stations.pipeline.geonames import (
    GAZETTEER_URL,
    GazetteerMissing,
    load_gazetteer,
    normalise_place_name,
)


def geonames_line(gid, name, alt, fclass, fcode, state, pop, lat="40.0", lng="-90.0"):
    cols = [str(gid), name, name, alt, lat, lng, fclass, fcode, "US", "", state]
    cols += ["", "", "", str(pop), "", "100", "America/Chicago", "2024-01-01"]
    return "\t".join(cols)


@pytest.mark.parametrize(
    ("raw", "normalised"),
    [
        ("ST LOUIS ", "saint louis"),
        ("St. Louis", "saint louis"),
        ("Saint Louis", "saint louis"),
        ("Ft Worth", "fort worth"),
        ("Ft. Worth", "fort worth"),
        ("Mt Vernon", "mount vernon"),
        ("Ste Genevieve", "sainte genevieve"),
        ("Mc Lean", "mclean"),
        ("MC DERMITT", "mcdermitt"),
        ("McLean", "mclean"),
        ("Winston-Salem", "winston salem"),
        ("O'Fallon", "ofallon"),
        ("  Big    Cabin  ", "big cabin"),
    ],
)
def test_normalise_place_name(raw, normalised):
    assert normalise_place_name(raw) == normalised


def test_only_populated_places_are_kept(fixtures_dir):
    gazetteer = load_gazetteer(fixtures_dir / "sample_geonames.txt")

    assert gazetteer.lookup("Lake Example", "MO") is None  # class H
    place, via = gazetteer.lookup("Saint Louis", "MO")
    assert (place.geonameid, via) == (4407066, MatchVia.PRIMARY)


def test_historical_places_are_skipped_and_alternate_names_are_a_fallback(fixtures_dir):
    gazetteer = load_gazetteer(fixtures_dir / "sample_geonames.txt")

    # "Hometown" (PPLH) is ignored; "New Hometown" lists "Hometown" as an alternate name.
    place, via = gazetteer.lookup("Hometown", "KS")
    assert (place.name, via) == ("New Hometown", MatchVia.ALTERNATE)


def test_tie_rule_population_then_lowest_geonameid(fixtures_dir):
    gazetteer = load_gazetteer(fixtures_dir / "sample_geonames.txt")

    place, _ = gazetteer.lookup("Springfield", "IL")
    # 4250542 has 114,394 people; 4250999 ties on population but has a higher id.
    assert place.geonameid == 4250542


def test_coordinates_keep_the_source_text(fixtures_dir):
    place, _ = load_gazetteer(fixtures_dir / "sample_geonames.txt").lookup("Springfield", "IL")

    assert (place.lat_text, place.lng_text, place.population) == ("39.80172", "-89.64371", 114394)


def test_population_zero_place_still_matches(fixtures_dir):
    place, via = load_gazetteer(fixtures_dir / "sample_geonames.txt").lookup("Tinyville", "TX")

    assert (place.population, via) == (0, MatchVia.PRIMARY)


def test_main_name_wins_over_another_places_alternate_name(tmp_path):
    path = tmp_path / "US.txt"
    path.write_text(
        geonames_line(1, "Alpha", "", "P", "PPL", "TX", 10)
        + "\n"
        + geonames_line(2, "Beta", "Alpha", "P", "PPL", "TX", 1000)
        + "\n",
        encoding="utf-8",
    )

    place, via = load_gazetteer(path).lookup("Alpha", "TX")
    assert (place.geonameid, via) == (1, MatchVia.PRIMARY)


def test_unknown_city_or_wrong_state_is_none(fixtures_dir):
    gazetteer = load_gazetteer(fixtures_dir / "sample_geonames.txt")

    assert gazetteer.lookup("Nowhereville", "KS") is None
    assert gazetteer.lookup("Springfield", "MO") is None


def test_missing_gazetteer_names_path_and_download_url(tmp_path):
    missing = tmp_path / "US.txt"

    with pytest.raises(GazetteerMissing) as exc:
        load_gazetteer(missing)

    assert str(missing) in str(exc.value)
    assert GAZETTEER_URL == "https://download.geonames.org/export/dump/US.zip"
    assert GAZETTEER_URL in str(exc.value)
