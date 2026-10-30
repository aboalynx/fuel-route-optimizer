"""`python manage.py test` runs the pytest suite, so Django's usual command sees the real tests.

Django's options map to pytest: verbosity 0 -> -q, 2 -> -v, 3 -> -vv; --failfast -> --exitfirst.
--keepdb is accepted but not used. Test labels become pytest paths (a path, or a dotted module or
package that exists on disk) or, otherwise, one -k expression. With no labels, pytest runs the
testpaths from pyproject.toml.
"""

from pathlib import Path


class PytestTestRunner:
    def __init__(self, verbosity=1, failfast=False, keepdb=False, **kwargs):
        self.verbosity = verbosity
        self.failfast = failfast
        self.keepdb = keepdb  # accepted for Django compatibility; pytest-django manages the DB

    @classmethod
    def add_arguments(cls, parser):
        # Django's default runner adds these; a custom runner has to add them itself.
        parser.add_argument(
            "--failfast",
            action="store_true",
            help="Stop at the first failure (pytest --exitfirst).",
        )
        parser.add_argument(
            "--keepdb", action="store_true", help="Accepted for compatibility; has no effect."
        )

    def pytest_args(self, test_labels) -> list[str]:
        args = {0: ["-q"], 1: []}.get(self.verbosity, ["-" + "v" * (self.verbosity - 1)])
        if self.failfast:
            args.append("--exitfirst")
        keywords = []
        for label in test_labels:
            path = _as_path(label)
            if path is None:
                keywords.append(label)
            else:
                args.append(path)
        if keywords:
            args += ["-k", " or ".join(keywords)]
        return args

    def run_tests(self, test_labels, **kwargs) -> int:
        """The number Django treats as the failure count: pytest's exit code."""
        import pytest

        return int(pytest.main(self.pytest_args(test_labels)))


def _as_path(label: str) -> str | None:
    """A pytest path for a path or dotted module/package label that exists, else None."""
    if Path(label.split("::", 1)[0]).exists():
        return label
    dotted = Path(*label.split("."))
    if dotted.is_dir():
        return dotted.as_posix()
    if dotted.with_suffix(".py").is_file():
        return dotted.with_suffix(".py").as_posix()
    return None
