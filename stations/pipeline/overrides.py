"""Reviewed override lists in data/overrides/ (pure, no Django).

- rejected_matches.csv (FR-022): a listed (city, state, matched place) becomes unmatched. It never
  supplies coordinates, because a wrong location is worse than a missing one.
- manual_coordinates.csv (FR-023): reviewed OpenStreetMap coordinates for a station ID. They win
  over any gazetteer result and are stored exactly as written.
"""

import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlparse

from stations.pipeline.clean import MAX_LISTED_PROBLEMS, US_STATE_CODES, ValidationProblem
from stations.pipeline.geonames import normalise_place_name

REJECTED_HEADER = ["city", "state", "matched_name", "reason"]
MANUAL_HEADER = ["opis_id", "lat", "lng", "source", "note"]

# Contiguous-US bounding box for manual coordinates.
LAT_RANGE = (Decimal("24"), Decimal("50"))
LNG_RANGE = (Decimal("-125"), Decimal("-66"))
OSM_HOSTS = frozenset({"openstreetmap.org", "www.openstreetmap.org"})

Key = tuple[str, str, str]  # (normalised city, state, normalised matched name)


class OverridesFileError(Exception):
    def __init__(self, problems: list[ValidationProblem], title: str = "Rejected-matches file"):
        self.problems = problems
        lines = [f"{title} has {len(problems)} problem(s):"]
        lines += [
            f"  line {p.line}, {p.column}, {p.value!r}: {p.reason}"
            for p in problems[:MAX_LISTED_PROBLEMS]
        ]
        if len(problems) > MAX_LISTED_PROBLEMS:
            lines.append(
                f"  … and {len(problems) - MAX_LISTED_PROBLEMS} more (total {len(problems)})"
            )
        super().__init__("\n".join(lines))


@dataclass(frozen=True)
class RejectedMatches:
    keys: frozenset[Key]

    @classmethod
    def empty(cls) -> "RejectedMatches":
        return cls(frozenset())

    def rejects(self, city: str, state: str, matched_name: str) -> bool:
        return _key(city, state, matched_name) in self.keys

    def __len__(self) -> int:
        return len(self.keys)


def load_rejected_matches(path: Path | None) -> RejectedMatches:
    """Validate and load the list; a missing file means no rejections."""
    if path is None or not Path(path).is_file():
        return RejectedMatches.empty()

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        header = [name.strip() for name in reader.fieldnames or []]
        missing = [name for name in REJECTED_HEADER if name not in header]
        if missing:
            raise OverridesFileError(
                [ValidationProblem(1, "header", ",".join(header), _missing(missing))]
            )

        problems: list[ValidationProblem] = []
        seen: dict[Key, int] = {}
        for raw in reader:
            line = reader.line_num
            values = {name.strip(): (value or "").strip() for name, value in raw.items() if name}
            row_problems = [
                ValidationProblem(line, column, values.get(column, ""), "missing")
                for column in REJECTED_HEADER
                if not values.get(column)
            ]
            state = values.get("state", "")
            if state and state not in US_STATE_CODES:
                row_problems.append(ValidationProblem(line, "state", state, "unknown state code"))
            if not row_problems:
                key = _key(values["city"], state, values["matched_name"])
                if key in seen:
                    row_problems.append(
                        ValidationProblem(
                            line, "city", values["city"], f"duplicate of line {seen[key]}"
                        )
                    )
                else:
                    seen[key] = line
            problems += row_problems

    if problems:
        raise OverridesFileError(problems)
    return RejectedMatches(frozenset(seen))


def _key(city: str, state: str, matched_name: str) -> Key:
    return (normalise_place_name(city), state.strip(), normalise_place_name(matched_name))


def _missing(columns: list[str]) -> str:
    return f"missing or renamed column: {', '.join(columns)}"


@dataclass(frozen=True)
class ManualCoordinate:
    line: int
    opis_id: int
    lat_text: str  # stored exactly as written
    lng_text: str
    source: str
    note: str


def load_manual_coordinates(path: Path | None, known_ids: set[int]) -> dict[int, ManualCoordinate]:
    """Validate and load reviewed coordinates; a missing file means no overrides."""
    if path is None or not Path(path).is_file():
        return {}

    title = "Manual-coordinates file"
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        header = [name.strip() for name in reader.fieldnames or []]
        missing = [name for name in MANUAL_HEADER if name not in header]
        if missing:
            raise OverridesFileError(
                [ValidationProblem(1, "header", ",".join(header), _missing(missing))], title
            )

        problems: list[ValidationProblem] = []
        entries: dict[int, ManualCoordinate] = {}
        for raw in reader:
            line = reader.line_num
            values = {name.strip(): (value or "").strip() for name, value in raw.items() if name}
            row_problems: list[ValidationProblem] = []

            def report(column: str, reason: str, values=values, line=line, out=row_problems):
                out.append(ValidationProblem(line, column, values.get(column, ""), reason))

            opis_id = _manual_id(values.get("opis_id", ""), known_ids, report)
            _coordinate(values.get("lat", ""), "lat", LAT_RANGE, report)
            _coordinate(values.get("lng", ""), "lng", LNG_RANGE, report)
            if not _is_osm_url(values.get("source", "")):
                report("source", "not an openstreetmap.org URL")
            if opis_id is not None and opis_id in entries:
                report("opis_id", f"duplicate of line {entries[opis_id].line}")

            problems += row_problems
            if not row_problems:
                entries[opis_id] = ManualCoordinate(
                    line=line,
                    opis_id=opis_id,
                    lat_text=values["lat"],
                    lng_text=values["lng"],
                    source=values["source"],
                    note=values.get("note", ""),
                )

    if problems:
        raise OverridesFileError(problems, title)
    return entries


def _manual_id(text: str, known_ids: set[int], report) -> int | None:
    if not text:
        report("opis_id", "missing")
        return None
    if not (text.isascii() and text.isdigit()):
        report("opis_id", "not an integer")
        return None
    if int(text) not in known_ids:
        report("opis_id", "not a US station in the price file")
        return None
    return int(text)


def _coordinate(text: str, column: str, bounds: tuple[Decimal, Decimal], report) -> None:
    try:
        value = Decimal(text)
    except InvalidOperation:
        value = None
    if value is None or not value.is_finite():
        report(column, "not a number")
    elif not bounds[0] <= value <= bounds[1]:
        report(column, f"outside the contiguous US ({bounds[0]} to {bounds[1]})")


def _is_osm_url(text: str) -> bool:
    url = urlparse(text)
    return url.scheme in {"http", "https"} and url.hostname in OSM_HOSTS
