from dataclasses import dataclass
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@dataclass(frozen=True)
class OutDirs:
    """Output paths for build_station_data, kept inside tmp_path."""

    fixture: Path
    unmatched: Path
    places: Path


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def out_dirs(tmp_path) -> OutDirs:
    """Temp output paths, so integration tests never touch committed files."""
    return OutDirs(
        fixture=tmp_path / "stations.json",
        unmatched=tmp_path / "unmatched_cities.csv",
        places=tmp_path / "us_places.csv.gz",
    )
