"""Byte-stable writers for the committed output files (pure, no Django).

Every writer goes through a temp file next to the target and os.replace, so a crash never
leaves a half-written file behind.
"""

import csv
import os
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import TextIO

from stations.pipeline.clean import StationRecord

UNMATCHED_HEADER = ["opis_id", "name", "city", "state"]


def write_unmatched_csv(stations: Iterable[StationRecord], path: Path) -> None:
    """Unmatched stations ordered by opis_id, UTF-8, '\\n' line endings."""

    def write(f: TextIO) -> None:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(UNMATCHED_HEADER)
        for station in sorted(stations, key=lambda s: s.opis_id):
            writer.writerow([station.opis_id, station.name, station.city, station.state])

    write_text_atomically(path, write)


def write_text_atomically(path: Path, write: Callable[[TextIO], None]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = temp_path_for(path)
    try:
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            write(f)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def temp_path_for(path: Path) -> Path:
    return Path(path).with_name(Path(path).name + ".tmp")
