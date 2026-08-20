"""S6 M8.2 - the layer boundaries, pinned.

The layering is: models < core < services/agents < api < main. Two rules are
enforced at TOP-LEVEL import scope (in-function imports stay allowed - they are
the documented call-time escape hatch for cross-layer calls like core.audit
appending to the services provenance ledger, and hoisting them is M8.3's
per-site decision, not a blanket rule):

1. Nothing under app/core may import app.services at top level. The one module
   that did - the 13-line FastAPI DI shim app/core/dependencies.py - was API
   plumbing living in the wrong layer and now lives at app/api/dependencies.py.
2. Nothing under app/core, app/services, app/agents, app/models or
   app/workforce (except its own api/ package) may import app.api at top
   level. M8.1 made this true by moving the realtime bus out of the ws route
   module.

AST-based, not import-based: deterministic, side-effect-free, and it reports
every violation with file and line instead of failing on the first.
"""
import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def _top_level_imports(path: Path):
    """(lineno, module) for every top-level import in ``path``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:  # body only: function/method-scoped imports excluded
        if isinstance(node, ast.ImportFrom) and node.module:
            yield node.lineno, node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name


def _violations(root: str, forbidden_prefix: str, allow=()):
    out = []
    for path in sorted((BACKEND / root).rglob("*.py")):
        rel = path.relative_to(BACKEND).as_posix()
        if any(rel.startswith(a) for a in allow):
            continue
        for lineno, module in _top_level_imports(path):
            if module == forbidden_prefix or module.startswith(forbidden_prefix + "."):
                out.append(f"{rel}:{lineno} imports {module}")
    return out


def test_core_does_not_import_services_at_top_level():
    assert _violations("app/core", "app.services") == []


def test_lower_layers_do_not_import_the_api_at_top_level():
    for root, allow in (
        ("app/core", ()),
        ("app/services", ()),
        ("app/agents", ()),
        ("app/models", ()),
        # workforce is a vertical slice: its own api/ package is API layer.
        ("app/workforce", ("app/workforce/api/",)),
    ):
        assert _violations(root, "app.api", allow=allow) == [], root


def test_the_relocated_di_shim_still_serves_its_consumers():
    from app.api.dependencies import get_llm_router, get_polystore_engine
    assert callable(get_llm_router) and callable(get_polystore_engine)
