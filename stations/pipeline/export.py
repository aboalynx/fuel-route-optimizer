"""Byte-stable writers for the committed output files (pure, no Django).

Every writer goes through a temp file next to the target and os.replace, so a crash never
leaves a half-written file behind.
"""

import csv
import gzip
import io
import os
from collections.abc import Iterable
from pathlib import Path

from stations.pipeline.build import PlaceIndexRow, UnmatchedStation

UNMATCHED_HEADER = ["opis_id", "name", "city", "state", "reason"]
PLACES_HEADER = ["normalised_name", "display_name", "state", "lat", "lng", "population"]


def write_unmatched_csv(unmatched: Iterable[UnmatchedStation], path: Path) -> None:
    """Unmatched stations with their reason, ordered by opis_id, UTF-8, '\\n' line endings."""
    rows = [
        [u.station.opis_id, u.station.name, u.station.city, u.station.state, u.reason_text]
        for u in sorted(unmatched, key=lambda u: u.station.opis_id)
    ]
    write_bytes_atomically(path, _csv_bytes(UNMATCHED_HEADER, rows))


def places_gz_bytes(rows: Iterable[PlaceIndexRow]) -> bytes:
    """The gzipped place lookup; mtime 0 and no stored filename, so bytes depend on content only."""
    csv_bytes = _csv_bytes(
        PLACES_HEADER,
        ([r.normalised_name, r.display_name, r.state, r.lat, r.lng, r.population] for r in rows),
    )
    buffer = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, mtime=0) as gz:
        gz.write(csv_bytes)
    return buffer.getvalue()


def write_places_gz(rows: Iterable[PlaceIndexRow], path: Path) -> None:
    write_bytes_atomically(path, places_gz_bytes(rows))


def write_bytes_atomically(path: Path, data: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = temp_path_for(path)
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def temp_path_for(path: Path) -> Path:
    return Path(path).with_name(Path(path).name + ".tmp")


def _csv_bytes(header: list[str], rows: Iterable[list]) -> bytes:
    text = io.StringIO(newline="")
    writer = csv.writer(text, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return text.getvalue().encode("utf-8")
