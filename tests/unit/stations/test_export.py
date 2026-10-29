"""T016: byte-stable unmatched-cities export (pure, no DB)."""

import gzip
import os
from decimal import Decimal

import pytest

from stations.pipeline.build import PlaceIndexRow
from stations.pipeline.clean import StationRecord
from stations.pipeline.export import write_places_gz, write_unmatched_csv


def station(opis_id, name, city, state):
    return StationRecord(
        opis_id=opis_id,
        name=name,
        address="",
        city=city,
        state=state,
        best_price=Decimal("3"),
        rows=(),
    )


STATIONS = [
    station(300, "ZED STOP", "Zed", "KS"),
    station(106, "GHOST GAS, INC", "Nowhereville", "KS"),
    station(42, "ÉCOLE FUEL", "Montréal Ville", "VT"),
]


def test_header_order_and_line_endings(tmp_path):
    path = tmp_path / "reports" / "unmatched_cities.csv"

    write_unmatched_csv(STATIONS, path)

    assert path.read_bytes().decode("utf-8") == (
        "opis_id,name,city,state\n"
        "42,ÉCOLE FUEL,Montréal Ville,VT\n"
        '106,"GHOST GAS, INC",Nowhereville,KS\n'
        "300,ZED STOP,Zed,KS\n"
    )


def test_two_writes_give_identical_bytes(tmp_path):
    first, second = tmp_path / "a.csv", tmp_path / "b.csv"

    write_unmatched_csv(STATIONS, first)
    write_unmatched_csv(list(reversed(STATIONS)), second)

    assert first.read_bytes() == second.read_bytes()


def test_failed_write_leaves_no_partial_file(tmp_path, monkeypatch):
    path = tmp_path / "unmatched_cities.csv"
    path.write_text("previous content\n")

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)

    with pytest.raises(OSError, match="disk full"):
        write_unmatched_csv(STATIONS, path)

    assert path.read_text() == "previous content\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["unmatched_cities.csv"]


# --- place lookup (US3, T025) ---------------------------------------------------------------


PLACE_ROWS = [
    PlaceIndexRow("springfield", "Springfield", "IL", "39.80172", "-89.64371", 114394),
    PlaceIndexRow("saint louis", "Saint Louis", "MO", "38.62727", "-90.19789", 301578),
]


def test_places_gzip_header_is_fixed(tmp_path):
    path = tmp_path / "us_places.csv.gz"

    write_places_gz(PLACE_ROWS, path)

    data = path.read_bytes()
    assert data[:2] == b"\x1f\x8b"
    assert data[3] & 0x08 == 0  # no FNAME flag: no original filename stored
    assert data[4:8] == b"\x00\x00\x00\x00"  # mtime 0


def test_places_gzip_content(tmp_path):
    path = tmp_path / "us_places.csv.gz"

    write_places_gz(PLACE_ROWS, path)

    assert gzip.decompress(path.read_bytes()).decode("utf-8") == (
        "normalised_name,display_name,state,lat,lng,population\n"
        "springfield,Springfield,IL,39.80172,-89.64371,114394\n"
        "saint louis,Saint Louis,MO,38.62727,-90.19789,301578\n"
    )


def test_places_two_writes_give_identical_bytes(tmp_path):
    first, second = tmp_path / "a.csv.gz", tmp_path / "b.csv.gz"

    write_places_gz(PLACE_ROWS, first)
    write_places_gz(PLACE_ROWS, second)

    assert first.read_bytes() == second.read_bytes()


def test_places_failed_write_leaves_no_partial_file(tmp_path, monkeypatch):
    path = tmp_path / "us_places.csv.gz"

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)

    with pytest.raises(OSError, match="disk full"):
        write_places_gz(PLACE_ROWS, path)

    assert list(tmp_path.iterdir()) == []
