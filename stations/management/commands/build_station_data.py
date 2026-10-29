"""Thin entry point: parse flags, call the rebuild service, print the report, map errors."""

import argparse
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from stations.pipeline.clean import PriceFileError
from stations.pipeline.geonames import GazetteerMissing
from stations.pipeline.overrides import OverridesFileError
from stations.services.station_data import LocatedShareTooLow, rebuild_station_data

DEFAULT_FIXTURE = Path(settings.BASE_DIR) / "stations" / "fixtures" / "stations.json"
DEFAULT_UNMATCHED = Path(settings.BASE_DIR) / "data" / "reports" / "unmatched_cities.csv"
DEFAULT_PLACES = Path(settings.BASE_DIR) / "data" / "places" / "us_places.csv.gz"
DEFAULT_REJECTED = Path(settings.BASE_DIR) / "data" / "overrides" / "rejected_matches.csv"


class Command(BaseCommand):
    help = (
        "Rebuild the station data set from the OPIS price file and the GeoNames gazetteer, "
        "then export the shipped fixture and the unmatched-cities report."
    )

    def add_arguments(self, parser):
        parser.add_argument("--csv", type=Path, default=Path(settings.FUEL_PRICES_CSV))
        parser.add_argument("--geonames", type=Path, default=Path(settings.GEONAMES_FILE))
        parser.add_argument(
            "--min-geocoded-pct",
            default="95",
            help="Minimum share of stations that must be located, 0-100 (default 95).",
        )
        parser.add_argument(
            "--rejected-matches",
            type=Path,
            default=DEFAULT_REJECTED,
            help="Reviewed matches to reject (default data/overrides/rejected_matches.csv).",
        )
        parser.add_argument(
            "--no-export",
            action="store_true",
            help="Store in the database but do not write the fixture or the place lookup.",
        )
        parser.add_argument(
            "--skip-osm",
            action="store_true",
            help="Accepted for forward compatibility; OSM matching arrives in feature 005.",
        )
        # Output locations; overridden by tests so committed files are never touched.
        parser.add_argument(
            "--fixture-out", type=Path, default=DEFAULT_FIXTURE, help=argparse.SUPPRESS
        )
        parser.add_argument(
            "--unmatched-out", type=Path, default=DEFAULT_UNMATCHED, help=argparse.SUPPRESS
        )
        parser.add_argument(
            "--places-out", type=Path, default=DEFAULT_PLACES, help=argparse.SUPPRESS
        )

    def handle(self, *args, **options):
        min_pct = _percentage(options["min_geocoded_pct"])
        try:
            outcome = rebuild_station_data(
                Path(options["csv"]),
                Path(options["geonames"]),
                min_geocoded_pct=min_pct,
                export=not options["no_export"],
                fixture_out=Path(options["fixture_out"]),
                unmatched_out=Path(options["unmatched_out"]),
                places_out=Path(options["places_out"]),
                rejected_matches_path=Path(options["rejected_matches"]),
            )
        except (PriceFileError, OverridesFileError, GazetteerMissing) as error:
            raise CommandError(str(error)) from error
        except LocatedShareTooLow as error:
            self.stdout.write(error.report_text)
            raise CommandError(str(error)) from error

        self.stdout.write(outcome.report_text)


def _percentage(value) -> Decimal:
    try:
        pct = Decimal(str(value))
    except InvalidOperation:
        pct = None
    if pct is None or not pct.is_finite() or not 0 <= pct <= 100:
        raise CommandError(f"--min-geocoded-pct must be a number from 0 to 100, got {value!r}")
    return pct
