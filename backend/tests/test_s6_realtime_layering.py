"""S6 M8.1 — the real-time broadcast bus is a service, not a route.

It used to live in ``app.api.routes.ws``, so core, agents and other services all
imported UPWARD into the presentation layer to publish an event. The bus now
lives in ``app.services.realtime``; these tests keep it there.
"""

import ast
import pathlib

import app.services.realtime as realtime
from app.api.routes.ws import manager as ws_manager

_SOURCE = pathlib.Path(realtime.__file__)


def _imported_modules(tree: ast.AST) -> list[str]:
    """Every module name imported anywhere in the file, top level or inside a
    function (the bus uses in-function imports to dodge cycles, so walking the
    whole tree is the only honest check)."""
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            # level > 0 is a relative import; app/services/realtime.py has none,
            # and a bare `from . import x` has module=None.
            names.append(node.module or "")
    return names


def test_bus_never_imports_the_presentation_layer():
    tree = ast.parse(_SOURCE.read_text(encoding="utf-8"))
    offenders = [
        m for m in _imported_modules(tree)
        if m == "app.api" or m.startswith("app.api.")
    ]
    assert not offenders, f"app/services/realtime.py imports upward into routes: {offenders}"


def test_routes_reexport_is_the_same_singleton():
    """app/main.py still starts the subscriber off the ws re-export, and one
    process must have exactly one connection registry."""
    assert ws_manager is realtime.manager
