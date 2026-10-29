"""T015: locating stations, report numbers and price ids (pure, no DB)."""

from decimal import Decimal

import pytest

from stations.enums import GeoSource, MatchVia, UnmatchedReason
from stations.pipeline.build import assign_price_ids, build, format_report, place_index_rows
from stations.pipeline.geonames import load_gazetteer, normalise_place_name
from stations.pipeline.overrides import OverridesFileError


@pytest.fixture
def result(fixtures_dir):
    return build(fixtures_dir / "sample_fuel.csv", fixtures_dir / "sample_geonames.txt")


@pytest.fixture
def rejected_result(fixtures_dir):
    return build(
        fixtures_dir / "sample_fuel.csv",
        fixtures_dir / "sample_geonames.txt",
        fixtures_dir / "sample_rejected_matches.csv",
    )


def test_counts_behind_the_report(result):
    assert result.rows_read == 21
    assert result.canadian_rows == 2
    assert result.us_price_rows == 19
    assert result.stations_kept == 15
    assert result.stations_with_several_prices == 3
    assert result.located_count == 14
    assert result.dropped_count == 1
    assert result.price_rows_stored == 18  # Nowhereville's row is excluded with its station


def test_unmatched_station_is_reported(result):
    assert [
        (u.station.opis_id, u.station.city, u.station.state, u.reason_text)
        for u in result.unmatched
    ] == [(106, "Nowhereville", "KS", "not found")]
    assert (result.not_found_count, result.rejected_count) == (1, 0)


def test_rejected_match_becomes_unmatched_with_reason(rejected_result):
    assert 105 not in {item.station.opis_id for item in rejected_result.located}
    rejected = {u.station.opis_id: u for u in rejected_result.unmatched}[105]
    assert rejected.reason is UnmatchedReason.REJECTED
    assert rejected.matched_name == "New Hometown"
    assert rejected.reason_text == "rejected match: New Hometown"
    assert (rejected_result.not_found_count, rejected_result.rejected_count) == (1, 1)
    assert rejected_result.located_count == 13
    assert rejected_result.price_rows_stored == 17


def test_non_listed_matches_are_unaffected(result, rejected_result):
    before = {i.station.opis_id: (i.place.geonameid, i.via) for i in result.located}
    after = {i.station.opis_id: (i.place.geonameid, i.via) for i in rejected_result.located}
    assert after == {k: v for k, v in before.items() if k != 105}


def test_missing_rejected_matches_file_means_no_rejections(result, fixtures_dir, tmp_path):
    missing = build(
        fixtures_dir / "sample_fuel.csv",
        fixtures_dir / "sample_geonames.txt",
        tmp_path / "none.csv",
    )
    assert missing == result


def test_malformed_rejected_matches_file_fails_before_lookup(fixtures_dir, tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("city,state,matched_name,reason\n,KS,X,y\n", encoding="utf-8")

    with pytest.raises(OverridesFileError):
        build(fixtures_dir / "sample_fuel.csv", tmp_path / "no_gazetteer_needed.txt", bad)


def test_stations_are_located_by_main_or_alternate_name(result):
    located = {item.station.opis_id: item for item in result.located}

    assert located[101].place.geonameid == 4407066  # "St. Louis" -> Saint Louis
    assert located[101].via is MatchVia.PRIMARY
    assert located[105].via is MatchVia.ALTERNATE  # "Hometown" -> New Hometown
    assert located[114].via is MatchVia.COMPACT  # "De Forest" -> DeForest
    assert located[115].via is MatchVia.COMPACT  # "Brookpark" -> Brook Park
    assert located[104].place.geonameid == located[111].place.geonameid == 4250542
    assert [item.station.opis_id for item in result.located] == sorted(located)


def test_located_share_and_threshold(result):
    assert result.located_pct == pytest.approx(93.333, abs=0.001)
    assert result.meets_threshold(Decimal("93"))
    assert not result.meets_threshold(Decimal("95"))
    assert result.meets_threshold(Decimal("0"))


def test_price_ids_follow_station_then_csv_line(result):
    ids = assign_price_ids(result.located)

    assert [pid for pid, _, _ in ids] == list(range(1, 19))
    assert [(opis_id, row.line) for _, opis_id, row in ids[:5]] == [
        (101, 2),
        (101, 3),
        (101, 4),
        (102, 5),
        (102, 6),
    ]
    assert [opis_id for _, opis_id, _ in ids] == sorted(opis_id for _, opis_id, _ in ids)


def test_report_uses_the_contract_labels(result):
    report = format_report(result, Decimal("50"), "data/reports/unmatched_cities.csv")

    assert report.splitlines() == [
        "Rows read 21 | Canadian rows dropped 2 | US price rows read 19 | price rows stored 18",
        "Stations kept 15 | with several prices 3",
        "Stations located 14 (93.3%, threshold 50%) | "
        "city_centroid 14 (100%) | manual 0 (0%) | osm 0 (0%)",
        "Stations dropped 1 (not found 1, rejected match 0) -> data/reports/unmatched_cities.csv",
    ]


def test_report_formats_thousands_and_decimal_threshold(result):
    report = format_report(result, Decimal("92.5"), "x.csv")

    assert "threshold 92.5%" in report


# --- place lookup (US3, T024) ---------------------------------------------------------------


def place_rows(fixtures_dir, result):
    gazetteer = load_gazetteer(fixtures_dir / "sample_geonames.txt")
    return place_index_rows(gazetteer, result.located)


def test_place_index_has_populated_and_matched_places(fixtures_dir, result):
    rows = place_rows(fixtures_dir, result)

    assert [(r.state, r.normalised_name) for r in rows] == [
        ("IL", "mclean"),
        ("IL", "springfield"),
        ("KS", "hometown"),  # alternate-name row: a station matched "Hometown" via New Hometown
        ("KS", "new hometown"),
        ("MO", "kansas city"),  # population > 0, no station needed
        ("MO", "saint louis"),
        ("OH", "brook park"),
        ("OH", "brookpark"),  # compact-tier row under the station's city key
        ("TX", "fort worth"),
        ("TX", "tinyville"),  # population 0, but a station matched it
        ("WI", "de forest"),  # compact-tier row
        ("WI", "deforest"),
    ]


def test_place_index_row_columns(fixtures_dir, result):
    rows = {(r.state, r.normalised_name): r for r in place_rows(fixtures_dir, result)}

    springfield = rows[("IL", "springfield")]
    assert (springfield.display_name, springfield.lat, springfield.lng, springfield.population) == (
        "Springfield",
        "39.80172",
        "-89.64371",
        114394,
    )
    assert rows[("KS", "hometown")].display_name == "New Hometown"
    assert rows[("WI", "de forest")].display_name == "DeForest"


def test_place_index_matches_station_coordinates(fixtures_dir, result):
    rows = {(r.state, r.normalised_name): r for r in place_rows(fixtures_dir, result)}

    for item in result.located:
        key = (item.station.state, normalise_place_name(item.station.city))
        assert (rows[key].lat, rows[key].lng) == (item.place.lat_text, item.place.lng_text)


def test_place_index_one_row_per_key_and_main_name_wins(tmp_path):
    path = tmp_path / "US.txt"
    lines = [
        ("1", "Alpha", "", "TX", "10"),
        ("2", "Beta", "Alpha,Gamma", "TX", "1000"),
        ("3", "Zero Town", "", "TX", "0"),
    ]
    path.write_text(
        "".join(
            "\t".join([gid, name, name, alt, "30.0", "-97.0", "P", "PPL", "US", "", st]
                      + ["", "", "", pop, "", "100", "America/Chicago", "2024-01-01"]) + "\n"
            for gid, name, alt, st, pop in lines
        ),
        encoding="utf-8",
    )  # fmt: skip

    rows = place_index_rows(load_gazetteer(path), [])

    keys = [(r.state, r.normalised_name) for r in rows]
    assert keys == [("TX", "alpha"), ("TX", "beta")]  # no alternate rows, no population-0 place
    assert rows[0].display_name == "Alpha"  # the main name, not Beta's alternate


def test_build_result_carries_the_place_index(result):
    assert len(result.places_index) == 12


# --- manual coordinates (FR-023) ------------------------------------------------------------


@pytest.fixture
def manual_result(fixtures_dir):
    return build(
        fixtures_dir / "sample_fuel.csv",
        fixtures_dir / "sample_geonames.txt",
        manual_coordinates_path=fixtures_dir / "sample_manual_coordinates.csv",
    )


def test_manual_override_wins_over_an_alternate_match(result, manual_result):
    assert {i.station.opis_id: i for i in result.located}[105].via is MatchVia.ALTERNATE

    item = {i.station.opis_id: i for i in manual_result.located}[105]
    assert item.geo_source is GeoSource.MANUAL
    assert (item.lat_text, item.lng_text) == ("38.94000", "-97.15000")
    assert item.place is None  # no gazetteer place: nothing leaks into the place lookup


def test_manual_override_does_not_touch_other_stations(result, manual_result):
    def coords(r):
        return {i.station.opis_id: (i.lat_text, i.lng_text, i.geo_source) for i in r.located}

    before, after = coords(result), coords(manual_result)
    assert {k: v for k, v in after.items() if k != 105} == {
        k: v for k, v in before.items() if k != 105
    }
    assert manual_result.located_count == result.located_count


def test_manual_station_adds_no_place_lookup_row(manual_result):
    keys = {(r.state, r.normalised_name) for r in manual_result.places_index}
    assert ("KS", "hometown") not in keys  # the alternate-name row came from station 105's match


def test_report_shows_share_by_source(manual_result):
    report = format_report(manual_result, Decimal("50"), "x.csv")

    assert "| city_centroid 13 (92.86%) | manual 1 (7.14%) | osm 0 (0%)" in report


def test_missing_manual_file_means_no_change(result, fixtures_dir, tmp_path):
    missing = build(
        fixtures_dir / "sample_fuel.csv",
        fixtures_dir / "sample_geonames.txt",
        manual_coordinates_path=tmp_path / "none.csv",
    )
    assert missing == result


def test_invalid_manual_file_fails_before_lookup(fixtures_dir, tmp_path):
    bad = tmp_path / "manual.csv"
    bad.write_text(
        "opis_id,lat,lng,source,note\n999,41,-72,https://www.openstreetmap.org/node/1,x\n"
    )

    with pytest.raises(OverridesFileError, match="line 2, opis_id"):
        build(fixtures_dir / "sample_fuel.csv", tmp_path / "no_gazetteer.txt", None, bad)
