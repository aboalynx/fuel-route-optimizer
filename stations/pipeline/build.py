"""Locate stations at their city centre and compute the rebuild report (pure, no Django).

Money stays Python Decimal throughout: no price arithmetic happens anywhere else.
"""

from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

from stations.enums import GeoSource, MatchVia
from stations.pipeline.clean import PriceRow, StationRecord, group_stations, read_price_rows
from stations.pipeline.geonames import Place, load_gazetteer


@dataclass(frozen=True)
class LocatedStation:
    station: StationRecord
    place: Place
    via: MatchVia


@dataclass(frozen=True)
class BuildResult:
    rows_read: int
    canadian_rows: int
    us_price_rows: int
    located: list[LocatedStation]  # sorted by opis_id
    unmatched: list[StationRecord]  # sorted by opis_id

    @property
    def stations_kept(self) -> int:
        return len(self.located) + len(self.unmatched)

    @property
    def stations_with_several_prices(self) -> int:
        stations = [item.station for item in self.located] + self.unmatched
        return sum(1 for station in stations if len(station.rows) > 1)

    @property
    def located_count(self) -> int:
        return len(self.located)

    @property
    def dropped_count(self) -> int:
        return len(self.unmatched)

    @property
    def price_rows_stored(self) -> int:
        return sum(len(item.station.rows) for item in self.located)

    @property
    def located_share(self) -> Fraction:
        if not self.stations_kept:
            return Fraction(0)
        return Fraction(self.located_count * 100, self.stations_kept)

    @property
    def located_pct(self) -> float:
        return float(self.located_share)

    def meets_threshold(self, min_pct: Decimal) -> bool:
        return self.located_share >= Fraction(str(min_pct))


def build(csv_path: Path, geonames_path: Path) -> BuildResult:
    """Validate the price file, group it by station and locate each station.

    Raises PriceFileError or GazetteerMissing before any work is done.
    """
    price_file = read_price_rows(csv_path)
    gazetteer = load_gazetteer(geonames_path)

    located: list[LocatedStation] = []
    unmatched: list[StationRecord] = []
    for station in group_stations(price_file.rows):
        match = gazetteer.lookup(station.city, station.state)
        if match is None:
            unmatched.append(station)
        else:
            place, via = match
            located.append(LocatedStation(station=station, place=place, via=via))

    return BuildResult(
        rows_read=price_file.rows_read,
        canadian_rows=price_file.canadian_rows,
        us_price_rows=len(price_file.rows),
        located=located,
        unmatched=unmatched,
    )


def assign_price_ids(located: list[LocatedStation]) -> list[tuple[int, int, PriceRow]]:
    """Explicit FuelPrice ids 1..N in (opis_id, CSV line) order, stable across rebuilds."""
    rows = sorted(
        ((item.station.opis_id, row) for item in located for row in item.station.rows),
        key=lambda pair: (pair[0], pair[1].line),
    )
    return [(pid, opis_id, row) for pid, (opis_id, row) in enumerate(rows, start=1)]


def format_report(
    result: BuildResult,
    min_pct: Decimal,
    unmatched_path: str,
    places_info: tuple[int, float] | None = None,
) -> str:
    """The rebuild report, with the exact labels of contracts/build_station_data.md."""
    by_source = {GeoSource.CITY_CENTROID: result.located_count, GeoSource.OSM: 0}
    source_shares = " | ".join(
        f"{source} {_pct(Fraction(count * 100, result.located_count or 1))}"
        for source, count in by_source.items()
    )
    lines = [
        f"Rows read {result.rows_read:,} | Canadian rows dropped {result.canadian_rows:,} | "
        f"US price rows read {result.us_price_rows:,} | "
        f"price rows stored {result.price_rows_stored:,}",
        f"Stations kept {result.stations_kept:,} | "
        f"with several prices {result.stations_with_several_prices:,}",
        f"Stations located {result.located_count:,} ({_pct(result.located_share)}, "
        f"threshold {_pct(Fraction(str(min_pct)))}) | {source_shares}",
        f"Stations dropped (city not found) {result.dropped_count:,} -> {unmatched_path}",
    ]
    if places_info is not None:
        count, megabytes = places_info
        lines.append(f"Places index {count:,} places, {megabytes:.1f} MB")
    return "\n".join(lines)


def _pct(value: Fraction) -> str:
    """One decimal place, without a trailing '.0' (e.g. '92.3%', '100%', '92.5%')."""
    text = f"{float(value):.1f}"
    return f"{text.removesuffix('.0')}%"
