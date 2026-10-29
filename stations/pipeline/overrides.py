"""The reviewed rejected-matches list, data/overrides/rejected_matches.csv (pure, no Django).

It only rejects matches: a listed (city, state, matched place) becomes unmatched. It never
supplies coordinates, because a wrong location is worse than a missing one (FR-022).
"""

import csv
from dataclasses import dataclass
from pathlib import Path

from stations.pipeline.clean import MAX_LISTED_PROBLEMS, US_STATE_CODES, ValidationProblem
from stations.pipeline.geonames import normalise_place_name

REJECTED_HEADER = ["city", "state", "matched_name", "reason"]

Key = tuple[str, str, str]  # (normalised city, state, normalised matched name)


class OverridesFileError(Exception):
    def __init__(self, problems: list[ValidationProblem]):
        self.problems = problems
        lines = [f"Rejected-matches file has {len(problems)} problem(s):"]
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
