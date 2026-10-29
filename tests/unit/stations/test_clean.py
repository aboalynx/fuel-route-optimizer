"""T013: price-file validation, cleaning and grouping (pure, no DB)."""

import csv
from decimal import Decimal

import pytest

from stations.pipeline.clean import (
    CANADIAN_CODES,
    EXPECTED_HEADER,
    US_STATE_CODES,
    CsvHeaderError,
    CsvValidationError,
    PriceFileError,
    group_stations,
    read_price_rows,
)

GOOD = ["7", "WOODSHED OF BIG CABIN", "I-44, EXIT 283", "Big Cabin", "OK", "307", "3.00733333"]


def write_csv(tmp_path, rows, header=EXPECTED_HEADER):
    path = tmp_path / "prices.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\r\n")
        writer.writerow(header)
        writer.writerows(rows)
    return path


def with_value(column, value, base=GOOD):
    row = list(base)
    row[EXPECTED_HEADER.index(column)] = value
    return row


def problems_for(tmp_path, rows):
    with pytest.raises(CsvValidationError) as exc:
        read_price_rows(write_csv(tmp_path, rows))
    return [(p.line, p.column, p.value, p.reason) for p in exc.value.problems]


# --- constants -----------------------------------------------------------------------------


def test_state_code_sets():
    assert len(US_STATE_CODES) == 51  # 50 states + DC
    assert "DC" in US_STATE_CODES
    expected_canadian = {
        "AB",
        "BC",
        "MB",
        "NB",
        "NL",
        "NS",
        "NT",
        "NU",
        "ON",
        "PE",
        "QC",
        "SK",
        "YT",
    }
    assert expected_canadian == CANADIAN_CODES
    assert not US_STATE_CODES & CANADIAN_CODES


def test_errors_share_one_base_class():
    assert issubclass(CsvHeaderError, PriceFileError)
    assert issubclass(CsvValidationError, PriceFileError)


# --- header --------------------------------------------------------------------------------


def test_renamed_header_column_fails_immediately(tmp_path):
    header = [*EXPECTED_HEADER[:-1], "Price"]
    path = write_csv(tmp_path, [with_value("Retail Price", "not even checked")], header=header)

    with pytest.raises(CsvHeaderError, match="missing or renamed column: Retail Price"):
        read_price_rows(path)


def test_header_names_are_stripped(tmp_path):
    header = [f" {name} " for name in EXPECTED_HEADER]
    result = read_price_rows(write_csv(tmp_path, [GOOD], header=header))

    assert len(result.rows) == 1


# --- row reasons ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("column", "value", "reason"),
    [
        ("OPIS Truckstop ID", "", "missing"),
        ("OPIS Truckstop ID", "7a", "not an integer"),
        ("OPIS Truckstop ID", "-7", "not an integer"),
        ("OPIS Truckstop ID", "7.0", "not an integer"),
        ("Rack ID", "", "missing"),
        ("Rack ID", "x1", "not an integer"),
        ("Retail Price", "", "missing"),
        ("Retail Price", "abc", "not a decimal"),
        ("Retail Price", "NaN", "not a decimal"),
        ("Retail Price", "Infinity", "not a decimal"),
        ("Retail Price", "0", "must be > 0"),
        ("Retail Price", "-3.1", "must be > 0"),
        ("Retail Price", "3.123456789", "too precise"),
        ("Retail Price", "12345.1", "too precise"),
        ("City", "", "missing"),
        ("City", "   ", "missing"),
        ("State", "", "missing"),
        ("State", "XX", "unknown state code"),
    ],
)
def test_each_malformed_value_is_reported(tmp_path, column, value, reason):
    # Values are stripped before validation, so the reported value is the stripped one.
    expected = [(2, column, value.strip(), reason)]
    assert problems_for(tmp_path, [with_value(column, value)]) == expected


def test_trailing_zeros_beyond_eight_places_are_not_too_precise(tmp_path):
    result = read_price_rows(write_csv(tmp_path, [with_value("Retail Price", "3.1000000000")]))

    assert result.rows[0].price == Decimal("3.1")


def test_same_id_with_a_different_city_conflicts(tmp_path):
    rows = [GOOD, with_value("City", "Vinita")]

    assert problems_for(tmp_path, rows) == [(3, "City", "Vinita", "conflicts with line 2")]


def test_same_id_with_a_different_state_conflicts(tmp_path):
    rows = [GOOD, with_value("State", "KS")]

    assert problems_for(tmp_path, rows) == [(3, "State", "KS", "conflicts with line 2")]


def test_every_problem_is_collected_before_failing(fixtures_dir):
    with pytest.raises(CsvValidationError) as exc:
        read_price_rows(fixtures_dir / "sample_fuel_bad.csv")

    assert [(p.line, p.column, p.reason) for p in exc.value.problems] == [
        (3, "Retail Price", "must be > 0"),
        (5, "City", "missing"),
    ]
    message = str(exc.value)
    assert "line 3, Retail Price, '-3.1': must be > 0" in message
    assert "line 5, City, '': missing" in message


def test_error_message_lists_first_50_and_the_total(tmp_path):
    rows = [
        with_value("Retail Price", "-1", with_value("OPIS Truckstop ID", str(i))) for i in range(60)
    ]

    with pytest.raises(CsvValidationError) as exc:
        read_price_rows(write_csv(tmp_path, rows))

    message = str(exc.value)
    assert exc.value.total == 60
    assert message.startswith("Price file has 60 problem(s):")
    assert "line 51," in message
    assert "line 52," not in message
    assert message.rstrip().endswith("… and 10 more (total 60)")


# --- clean rows ----------------------------------------------------------------------------


def test_canadian_rows_are_counted_not_reported(fixtures_dir):
    result = read_price_rows(fixtures_dir / "sample_fuel.csv")

    assert result.rows_read == 19
    assert result.canadian_rows == 2
    assert len(result.rows) == 17
    assert not {row.state for row in result.rows} & CANADIAN_CODES


def test_values_are_stripped_and_prices_exact(fixtures_dir):
    rows = read_price_rows(fixtures_dir / "sample_fuel.csv").rows
    first = rows[0]

    assert (first.line, first.opis_id, first.city, first.state) == (2, 101, "St. Louis", "MO")
    assert isinstance(first.price, Decimal)
    assert rows[1].price == Decimal("3.00733333")
    assert all(row.city == row.city.strip() for row in rows)


# --- grouping ------------------------------------------------------------------------------


def test_group_stations_one_record_per_id_sorted(fixtures_dir):
    stations = group_stations(read_price_rows(fixtures_dir / "sample_fuel.csv").rows)

    ids = [s.opis_id for s in stations]
    assert ids == sorted(ids)
    assert len(ids) == len(set(ids)) == 13


def test_group_stations_min_price_first_row_identity_and_all_rows(fixtures_dir):
    stations = {
        s.opis_id: s for s in group_stations(read_price_rows(fixtures_dir / "sample_fuel.csv").rows)
    }

    st_louis = stations[101]
    assert st_louis.best_price == Decimal("3.00733333")
    assert [row.line for row in st_louis.rows] == [2, 3, 4]
    assert (st_louis.address, st_louis.city, st_louis.state) == ("I-44, EXIT 1", "St. Louis", "MO")

    assert stations[102].best_price == Decimal("3.899")
    assert len(stations[102].rows) == 2  # exact duplicates are kept
    assert stations[103].name == "LOVES TRAVEL STOP #5"  # first spelling wins
