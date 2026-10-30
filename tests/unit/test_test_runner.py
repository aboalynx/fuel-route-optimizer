"""`python manage.py test` runs the pytest suite: option and label mapping."""

import pytest

from config.test_runner import PytestTestRunner


def args(labels=(), **options):
    return PytestTestRunner(**options).pytest_args(list(labels))


@pytest.mark.parametrize(
    ("verbosity", "expected"), [(0, ["-q"]), (1, []), (2, ["-v"]), (3, ["-vv"])]
)
def test_verbosity(verbosity, expected):
    assert args(verbosity=verbosity) == expected


def test_failfast_stops_at_the_first_failure():
    assert args(failfast=True) == ["--exitfirst"]


def test_keepdb_and_other_django_options_are_accepted_and_ignored():
    assert args(keepdb=True, interactive=False, parallel=0, testrunner=None) == []


def test_paths_and_dotted_modules_become_paths():
    assert args(["tests/unit/routing"]) == ["tests/unit/routing"]
    assert args(["tests.unit.routing"]) == ["tests/unit/routing"]
    assert args(["tests.unit.routing.test_cached"]) == ["tests/unit/routing/test_cached.py"]
    assert args(["tests/unit/routing/test_cached.py::test_hit_makes_no_call"]) == [
        "tests/unit/routing/test_cached.py::test_hit_makes_no_call"
    ]


def test_other_labels_become_a_keyword_expression():
    assert args(["cache", "osrm"]) == ["-k", "cache or osrm"]


def test_no_labels_runs_the_configured_testpaths():
    assert args([]) == []


def test_django_options_are_registered():
    import argparse

    parser = argparse.ArgumentParser()
    PytestTestRunner.add_arguments(parser)
    options = vars(parser.parse_args(["--failfast", "--keepdb"]))
    assert options == {"failfast": True, "keepdb": True}
