"""Validate, clean and group the OPIS price file (pure, no Django).

The whole file is validated before anything is returned: every problem is collected and
reported in one error, so a failed run never writes partial data (FR-020).
"""

import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

EXPECTED_HEADER = [
    "OPIS Truckstop ID",
    "Truckstop Name",
    "Address",
    "City",
    "State",
    "Rack ID",
    "Retail Price",
]

# 50 states + DC.
US_STATE_CODES = frozenset(
    {
        "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL",
        "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE",
        "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD",
        "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    }
)  # fmt: skip
# Provinces and territories: valid rows, dropped silently.
CANADIAN_CODES = frozenset(
    {"AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT"}
)

# DecimalField(max_digits=12, decimal_places=8): anything outside would be rounded on save.
MAX_DECIMAL_PLACES = 8
MAX_INTEGER_DIGITS = 4
MAX_LISTED_PROBLEMS = 50


@dataclass(frozen=True)
class PriceRow:
    line: int
    opis_id: int
    name: str
    address: str
    city: str
    state: str
    rack_id: int
    price: Decimal


@dataclass(frozen=True)
class StationRecord:
    opis_id: int
    name: str
    address: str
    city: str
    state: str
    best_price: Decimal
    rows: tuple[PriceRow, ...]


@dataclass(frozen=True)
class ValidationProblem:
    line: int
    column: str
    value: str
    reason: str


@dataclass(frozen=True)
class PriceFile:
    rows: list[PriceRow]  # US rows only, in file order
    canadian_rows: int
    rows_read: int


class PriceFileError(Exception):
    """The price file cannot be used; nothing must be written."""


class CsvHeaderError(PriceFileError):
    def __init__(self, missing: list[str]):
        self.missing = missing
        super().__init__(f"missing or renamed column: {', '.join(missing)}")


class CsvValidationError(PriceFileError):
    def __init__(self, problems: list[ValidationProblem]):
        self.problems = problems
        self.total = len(problems)
        super().__init__(self._message())

    def _message(self) -> str:
        lines = [f"Price file has {self.total} problem(s):"]
        lines += [
            f"  line {p.line}, {p.column}, {p.value!r}: {p.reason}"
            for p in self.problems[:MAX_LISTED_PROBLEMS]
        ]
        hidden = self.total - MAX_LISTED_PROBLEMS
        if hidden > 0:
            lines.append(f"  … and {hidden} more (total {self.total})")
        return "\n".join(lines)


def read_price_rows(path: Path) -> PriceFile:
    """Read and validate the whole price file; raise PriceFileError on any problem."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = [name.strip() for name in next(reader, [])]
        missing = [name for name in EXPECTED_HEADER if name not in header]
        if missing:
            raise CsvHeaderError(missing)
        index = {name: header.index(name) for name in EXPECTED_HEADER}

        problems: list[ValidationProblem] = []
        rows: list[PriceRow] = []
        first_place: dict[int, tuple[int, str, str]] = {}  # opis_id -> (line, city, state)
        canadian = rows_read = 0

        for raw in reader:
            rows_read += 1
            values = {name: (raw[i].strip() if i < len(raw) else "") for name, i in index.items()}
            row, row_problems = _check_row(reader.line_num, values, first_place)
            problems += row_problems
            if row is None:
                continue
            if row.state in CANADIAN_CODES:
                canadian += 1
                continue
            rows.append(row)

    if problems:
        raise CsvValidationError(problems)
    return PriceFile(rows=rows, canadian_rows=canadian, rows_read=rows_read)


def group_stations(rows: list[PriceRow]) -> list[StationRecord]:
    """One record per OPIS ID, sorted by ID: minimum price, first row's identity, all rows."""
    grouped: dict[int, list[PriceRow]] = {}
    for row in rows:
        grouped.setdefault(row.opis_id, []).append(row)

    stations = []
    for opis_id in sorted(grouped):
        station_rows = grouped[opis_id]
        first = station_rows[0]
        stations.append(
            StationRecord(
                opis_id=opis_id,
                name=first.name,
                address=first.address,
                city=first.city,
                state=first.state,
                best_price=min(row.price for row in station_rows),
                rows=tuple(station_rows),
            )
        )
    return stations


def _check_row(
    line: int, values: dict[str, str], first_place: dict[int, tuple[int, str, str]]
) -> tuple[PriceRow | None, list[ValidationProblem]]:
    """Validate one row; return the parsed row (or None) and its problems."""
    problems: list[ValidationProblem] = []

    def report(column: str, reason: str) -> None:
        problems.append(ValidationProblem(line, column, values[column], reason))

    opis_id = _parse_id(values, "OPIS Truckstop ID", report)
    rack_id = _parse_id(values, "Rack ID", report)
    price = _parse_price(values["Retail Price"], report)
    for column in ("City", "State"):
        if not values[column]:
            report(column, "missing")
    state = values["State"]
    if state and state not in US_STATE_CODES and state not in CANADIAN_CODES:
        report("State", "unknown state code")

    if opis_id is not None and values["City"] and state:
        first = first_place.setdefault(opis_id, (line, values["City"], state))
        for column, expected in (("City", first[1]), ("State", first[2])):
            if values[column] != expected:
                report(column, f"conflicts with line {first[0]}")

    if problems:
        return None, problems
    row = PriceRow(
        line=line,
        opis_id=opis_id,
        name=values["Truckstop Name"],
        address=values["Address"],
        city=values["City"],
        state=state,
        rack_id=rack_id,
        price=price,
    )
    return row, problems


def _parse_id(values: dict[str, str], column: str, report) -> int | None:
    text = values[column]
    if not text:
        report(column, "missing")
        return None
    if not (text.isascii() and text.isdigit()):
        report(column, "not an integer")
        return None
    return int(text)


def _parse_price(text: str, report) -> Decimal | None:
    if not text:
        report("Retail Price", "missing")
        return None
    try:
        price = Decimal(text)
    except InvalidOperation:
        price = None
    if price is None or not price.is_finite():
        report("Retail Price", "not a decimal")
        return None
    if price <= 0:
        report("Retail Price", "must be > 0")
        return None
    exponent = price.normalize().as_tuple().exponent
    if -exponent > MAX_DECIMAL_PLACES or price.adjusted() + 1 > MAX_INTEGER_DIGITS:
        report("Retail Price", "too precise")
        return None
    return price
