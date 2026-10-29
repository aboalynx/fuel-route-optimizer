"""FR-022: the reviewed rejected-matches list (pure, no DB)."""

from pathlib import Path

import pytest

from stations.pipeline.overrides import (
    REJECTED_HEADER,
    OverridesFileError,
    RejectedMatches,
    load_rejected_matches,
)


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


def test_shipped_list_rejects_willington():
    repo = Path(__file__).resolve().parents[3]
    rejected = load_rejected_matches(repo / "data" / "overrides" / "rejected_matches.csv")

    assert rejected.rejects("Willington", "CT", "Millington")
