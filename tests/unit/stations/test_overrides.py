"""FR-022: the reviewed rejected-matches list (pure, no DB)."""

from pathlib import Path

import pytest

from stations.pipeline.overrides import (
    MANUAL_HEADER,
    REJECTED_HEADER,
    OverridesFileError,
    RejectedMatches,
    load_manual_coordinates,
    load_rejected_matches,
)

REPO = Path(__file__).resolve().parents[3]
OSM = "https://www.openstreetmap.org/node/10857848288"


def write(tmp_path, text):
    path = tmp_path / "rejected_matches.csv"
    path.write_text(text, encoding="utf-8")
    return path


def test_header():
    assert REJECTED_HEADER == ["city", "state", "matched_name", "reason"]


def test_listed_match_is_rejected_after_normalisation(tmp_path):
    rejected = load_rejected_matches(
        write(tmp_path, "city,state,matched_name,reason\nWillington,CT,Millington,28 miles off\n")
    )

    assert rejected.rejects("WILLINGTON ", "CT", "Millington")
    assert not rejected.rejects("Willington", "CT", "Willington Hill")  # other matched place
    assert not rejected.rejects("Willington", "NY", "Millington")  # other state
    assert len(rejected) == 1


def test_missing_file_means_no_rejections(tmp_path):
    rejected = load_rejected_matches(tmp_path / "does_not_exist.csv")

    assert rejected == RejectedMatches.empty()
    assert len(rejected) == 0


def test_every_problem_is_collected(tmp_path):
    path = write(
        tmp_path,
        "city,state,matched_name,reason\n"
        ",CT,Millington,x\n"  # line 2: empty city
        "Willington,XX,Millington,x\n"  # line 3: unknown state
        "Willington,CT,,x\n"  # line 4: empty matched name
        "Willington,CT,Millington,\n"  # line 5: empty reason
        "Dundee,IL,West Dundee,ok\n"  # line 6: valid
        "dundee ,IL,West Dundee,again\n",  # line 7: duplicate of line 6 after normalisation
    )

    with pytest.raises(OverridesFileError) as exc:
        load_rejected_matches(path)

    assert [(p.line, p.column, p.reason) for p in exc.value.problems] == [
        (2, "city", "missing"),
        (3, "state", "unknown state code"),
        (4, "matched_name", "missing"),
        (5, "reason", "missing"),
        (7, "city", "duplicate of line 6"),
    ]
    assert str(exc.value).startswith("Rejected-matches file has 5 problem(s):")


def test_wrong_header_fails(tmp_path):
    path = write(tmp_path, "city,state,place,reason\nWillington,CT,Millington,x\n")

    with pytest.raises(OverridesFileError, match="missing or renamed column: matched_name"):
        load_rejected_matches(path)


def test_shipped_rejected_list_is_header_only_and_valid():
    rejected = load_rejected_matches(REPO / "data" / "overrides" / "rejected_matches.csv")

    assert len(rejected) == 0


# --- manual coordinates (FR-023) ------------------------------------------------------------


def write_manual(tmp_path, *rows, header="opis_id,lat,lng,source,note"):
    path = tmp_path / "manual_coordinates.csv"
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")
    return path


def test_manual_header():
    assert MANUAL_HEADER == ["opis_id", "lat", "lng", "source", "note"]


def test_manual_coordinates_keep_the_text_exactly(tmp_path):
    path = write_manual(tmp_path, f"52623,41.9256406,-72.2598092,{OSM},Exit 71")

    manual = load_manual_coordinates(path, known_ids={52623})

    entry = manual[52623]
    assert (entry.line, entry.lat_text, entry.lng_text, entry.source, entry.note) == (
        2,
        "41.9256406",
        "-72.2598092",
        OSM,
        "Exit 71",
    )


def test_missing_manual_file_means_no_overrides(tmp_path):
    assert load_manual_coordinates(tmp_path / "none.csv", known_ids={1}) == {}


@pytest.mark.parametrize(
    ("row", "column", "reason"),
    [
        (f"99999,41.9,-72.2,{OSM},x", "opis_id", "not a US station in the price file"),
        (f"52a,41.9,-72.2,{OSM},x", "opis_id", "not an integer"),
        (f"52623,51.0,-72.2,{OSM},x", "lat", "outside the contiguous US (24 to 50)"),
        (f"52623,23.9,-72.2,{OSM},x", "lat", "outside the contiguous US (24 to 50)"),
        (f"52623,41.9,-126,{OSM},x", "lng", "outside the contiguous US (-125 to -66)"),
        (f"52623,41.9,-65.9,{OSM},x", "lng", "outside the contiguous US (-125 to -66)"),
        (f"52623,north,-72.2,{OSM},x", "lat", "not a number"),
        (
            "52623,41.9,-72.2,https://maps.google.com/?q=1,x",
            "source",
            "not an openstreetmap.org URL",
        ),
        ("52623,41.9,-72.2,openstreetmap.org/node/1,x", "source", "not an openstreetmap.org URL"),
        (
            "52623,41.9,-72.2,https://evil.example/openstreetmap.org,x",
            "source",
            "not an openstreetmap.org URL",
        ),
    ],
)
def test_each_invalid_override_is_reported_with_its_line(tmp_path, row, column, reason):
    path = write_manual(tmp_path, f"52623,41.92,-72.25,{OSM},ok", row)

    with pytest.raises(OverridesFileError) as exc:
        load_manual_coordinates(path, known_ids={52623})

    found = [(p.line, p.column, p.reason) for p in exc.value.problems]
    assert (3, column, reason) in found
    assert "line 3" in str(exc.value)
    assert str(exc.value).startswith("Manual-coordinates file has")


def test_duplicate_override_is_reported(tmp_path):
    path = write_manual(tmp_path, f"52623,41.9,-72.2,{OSM},a", f"52623,41.8,-72.1,{OSM},b")

    with pytest.raises(OverridesFileError) as exc:
        load_manual_coordinates(path, known_ids={52623})

    assert [(p.line, p.column, p.reason) for p in exc.value.problems] == [
        (3, "opis_id", "duplicate of line 2")
    ]


def test_manual_header_must_match(tmp_path):
    path = write_manual(
        tmp_path, f"52623,41.9,-72.2,{OSM},x", header="opis_id,latitude,lng,source,note"
    )

    with pytest.raises(OverridesFileError, match="missing or renamed column: lat"):
        load_manual_coordinates(path, known_ids={52623})


def test_shipped_manual_coordinates_place_willington_at_exit_71():
    manual = load_manual_coordinates(
        REPO / "data" / "overrides" / "manual_coordinates.csv", known_ids={52623, 71659}
    )

    assert sorted(manual) == [52623, 71659]
    assert {(m.lat_text, m.lng_text) for m in manual.values()} == {("41.9256406", "-72.2598092")}
