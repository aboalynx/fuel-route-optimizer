"""Rebuild service: run the pure pipeline, store the stations, export the shipped files.

Run phases (research R7), so a failure never leaves partial data:
1. build()             - validates everything; raises before anything is written
2. unmatched CSV       - always written once the build succeeds (it is what you fix)
3. threshold check     - raises LocatedShareTooLow; DB and fixture untouched
4. atomic DB write     - delete, insert stations, insert prices with explicit ids,
                         dump the fixture and the place lookup to temp files
5. after the block     - swap the temp files into place
"""

import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from django.core.management import call_command
from django.db import transaction

from stations.models import FuelPrice, FuelStation
from stations.pipeline.build import BuildResult, assign_price_ids, build, format_report
from stations.pipeline.export import places_gz_bytes, temp_path_for, write_unmatched_csv

BYTES_PER_MB = 1_000_000


class LocatedShareTooLow(Exception):
    def __init__(self, result: BuildResult, min_pct: Decimal, report_text: str):
        self.result = result
        self.min_pct = min_pct
        self.report_text = report_text
        super().__init__(
            f"Located share {result.located_pct:.1f}% is below the minimum of {min_pct}% "
            f"(--min-geocoded-pct). Nothing was stored or exported."
        )


@dataclass(frozen=True)
class RebuildOutcome:
    result: BuildResult
    report_text: str


def rebuild_station_data(
    csv_path: Path,
    geonames_path: Path,
    *,
    min_geocoded_pct: Decimal,
    export: bool,
    fixture_out: Path,
    unmatched_out: Path,
    places_out: Path,
    rejected_matches_path: Path | None = None,
    manual_coordinates_path: Path | None = None,
) -> RebuildOutcome:
    result = build(csv_path, geonames_path, rejected_matches_path, manual_coordinates_path)

    write_unmatched_csv(result.unmatched, unmatched_out)
    unmatched_display = _display(unmatched_out)

    if not result.meets_threshold(min_geocoded_pct):
        report_text = format_report(result, min_geocoded_pct, unmatched_display)
        raise LocatedShareTooLow(result, min_geocoded_pct, report_text)

    fixture_tmp, places_tmp = temp_path_for(fixture_out), temp_path_for(places_out)
    places_info = None
    try:
        with transaction.atomic():
            _store(result)
            if export:
                Path(fixture_out).parent.mkdir(parents=True, exist_ok=True)
                call_command(
                    "dumpdata",
                    "stations.FuelStation",
                    "stations.FuelPrice",
                    indent=2,
                    output=str(fixture_tmp),
                    verbosity=0,
                )
                places = places_gz_bytes(result.places_index)
                Path(places_out).parent.mkdir(parents=True, exist_ok=True)
                places_tmp.write_bytes(places)
                places_info = (len(result.places_index), len(places) / BYTES_PER_MB)
        if export:
            os.replace(fixture_tmp, fixture_out)
            os.replace(places_tmp, places_out)
    finally:
        fixture_tmp.unlink(missing_ok=True)
        places_tmp.unlink(missing_ok=True)

    report_text = format_report(result, min_geocoded_pct, unmatched_display, places_info)
    return RebuildOutcome(result=result, report_text=report_text)


def _store(result: BuildResult) -> None:
    FuelPrice.objects.all().delete()
    FuelStation.objects.all().delete()

    FuelStation.objects.bulk_create(
        FuelStation(
            opis_id=item.station.opis_id,
            name=item.station.name,
            address=item.station.address,
            city=item.station.city,
            state=item.station.state,
            lat=float(item.lat_text),
            lng=float(item.lng_text),
            geo_source=item.geo_source,
            match_score=None,
            best_price=item.station.best_price,
        )
        for item in result.located
    )
    FuelPrice.objects.bulk_create(
        FuelPrice(
            id=price_id,
            station_id=opis_id,
            rack_id=row.rack_id,
            raw_name=row.name,
            price=row.price,
        )
        for price_id, opis_id, row in assign_price_ids(result.located)
    )


def _display(path: Path) -> str:
    """Repo-relative path for the report when possible, otherwise the path as given."""
    try:
        return os.path.relpath(path)
    except ValueError:
        return str(path)
