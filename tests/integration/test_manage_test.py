"""`python manage.py test <path>` collects and runs the pytest suite (real subprocess)."""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_manage_py_test_runs_pytest_on_a_path():
    result = subprocess.run(
        [sys.executable, "manage.py", "test", "tests/unit/routing", "-v", "0"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    passed = re.search(r"(\d+) passed", output)
    assert passed and int(passed.group(1)) > 0, output
