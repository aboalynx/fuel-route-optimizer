"""T016: byte-stable unmatched-cities export (pure, no DB)."""

import os
from decimal import Decimal

import pytest

from stations.pipeline.clean import StationRecord
from stations.pipeline.export import write_unmatched_csv


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
