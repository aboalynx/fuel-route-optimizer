"""T006: the API error codes (pure, no Django)."""

import ast
import inspect

import api.enums
from api.enums import ErrorCode


def test_error_code_values():
    assert [code.value for code in ErrorCode] == [
        "invalid_input",
        "location_not_found",
        "location_outside_us",
        "same_location",
        "infeasible_route",
        "routing_unavailable",
        "station_data_missing",
        "place_data_missing",
        "internal_error",
    ]


def test_enums_module_does_not_import_django():
    tree = ast.parse(inspect.getsource(api.enums))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)

    assert not any(name.split(".")[0] == "django" for name in modules)
