"""T015: locating stations, report numbers and price ids (pure, no DB)."""

from decimal import Decimal

import pytest

from stations.enums import MatchVia
from stations.pipeline.build import assign_price_ids, build, format_report, place_index_rows
from stations.pipeline.geonames import load_gazetteer, normalise_place_name


@pytest.fixture
def result(fixtures_dir):
    return build(fixtures_dir / "sample_fuel.csv", fixtures_dir / "sample_geonames.txt")


def test_counts_behind_the_report(result):
    assert result.rows_read == 19
    assert result.canadian_rows == 2
    assert result.us_price_rows == 17
    assert result.stations_kept == 13
    assert result.stations_with_several_prices == 3
    assert result.located_count == 12
    assert result.dropped_count == 1
    assert result.price_rows_stored == 16  # Nowhereville's row is excluded with its station


def test_unmatched_station_is_reported(result):
    assert [(s.opis_id, s.city, s.state) for s in result.unmatched] == [(106, "Nowhereville", "KS")]


def test_stations_are_located_by_main_or_alternate_name(result):
    located = {item.station.opis_id: item for item in result.located}

    assert located[101].place.geonameid == 4407066  # "St. Louis" -> Saint Louis
    assert located[101].via is MatchVia.PRIMARY
    assert located[105].via is MatchVia.ALTERNATE  # "Hometown" -> New Hometown
    assert located[104].place.geonameid == located[111].place.geonameid == 4250542
    assert [item.station.opis_id for item in result.located] == sorted(located)


def test_located_share_and_threshold(result):
    assert result.located_pct == pytest.approx(92.307, abs=0.001)
    assert result.meets_threshold(Decimal("92"))
    assert not result.meets_threshold(Decimal("95"))
    assert result.meets_threshold(Decimal("0"))


def test_price_ids_follow_station_then_csv_line(result):
    ids = assign_price_ids(result.located)

    assert [pid for pid, _, _ in ids] == list(range(1, 17))
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
        "Rows read 19 | Canadian rows dropped 2 | US price rows read 17 | price rows stored 16",
        "Stations kept 13 | with several prices 3",
        "Stations located 12 (92.3%, threshold 50%) | city_centroid 100% | osm 0%",
        "Stations dropped (city not found) 1 -> data/reports/unmatched_cities.csv",
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
        ("TX", "fort worth"),
        ("TX", "tinyville"),  # population 0, but a station matched it
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
    assert len(result.places_index) == 8
