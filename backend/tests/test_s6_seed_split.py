"""S6 M2.3 + M2.5 - the seeders' logging contract, and the seam that blocks a split.

M2.5 (done): the ten department seeders logged through bare ``print()``, so every
seed line went to stdout unconditionally - invisible to the log pipeline, unfiltered
by level, and noise in any process that seeds as a side effect. 62 calls across the
ten files are now ``logger.info`` on a module logger. The tripwire below keeps them
out; it walks the AST rather than grepping, because ``AgentBluePRINT(`` and friends
make a text search for ``print(`` lie (that exact false positive is why the core
seeder appeared to have one print when it has none).

M2.3 (REFUTED): ``app/core/seed.py`` was to be split into a package. It was not,
and ``test_now_is_readable_where_seed_departments_reads_it`` is the reason, pinned
as an executable fact. ``NOW`` is a module global that ``seed_database()`` sets at
call time and six builders read - 33,995 of the module's 61,284 bytes (55%) sit in
functions that close over it. Two tests outside this file
(``test_department_contract.py``, ``test_s6_department_registry.py``) drive the
pure builders by ASSIGNING that global from the outside::

    seed.NOW = datetime.now(timezone.utc)
    seed.seed_departments()

Under a package, ``from .org import seed_departments`` re-exports the FUNCTION but
not its globals: ``seed.NOW = x`` writes to the package object while the builder
keeps reading ``org.NOW``, still ``None``. Both callers then die on
``unsupported operand type(s) for -: 'NoneType' and 'datetime.timedelta'`` - at
runtime, in a data fixture, with a stack trace that names neither the split nor the
assignment. Preserving the contract would need each submodule to reach back into
its own package for the value at call time, which is a worse object than the
monolith it replaces.

The split is worth doing only AFTER ``NOW`` stops being a mutable module global -
pass the instant in, or hold it in a ``contextvars.ContextVar``. That change edits
the two callers above, so it belongs to whoever owns them.
"""
import ast
import pathlib

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[1]
DEPARTMENTS = ["hr", "finance", "legal", "sales", "support",
               "operations", "engineering", "healthcare", "lending", "procurement"]


def _seed_files():
    """Every seeder this milestone owns: the ten departments + the core fixture.

    Written to survive M2.3 landing later - ``app/core/seed`` is picked up whether
    it stays a module or becomes a package.
    """
    files = [BACKEND / "app" / dept / "seed.py" for dept in DEPARTMENTS]
    core = BACKEND / "app" / "core" / "seed.py"
    files += [core] if core.is_file() else sorted((BACKEND / "app" / "core" / "seed").glob("*.py"))
    return files


def _print_calls(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [node.lineno for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "print"]


@pytest.mark.parametrize("path", _seed_files(), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_seeders_log_instead_of_printing(path):
    """No escape hatch: zero bare print() in a seeder, no exceptions granted.

    A seeder runs on startup, in CI, and inside pytest. print() cannot be silenced,
    tagged, or routed, so one added here is a permanent stdout leak everywhere.
    """
    assert path.is_file(), f"{path} vanished - update DEPARTMENTS or _seed_files()"
    lines = _print_calls(path)
    assert not lines, (
        f"{path.relative_to(BACKEND)} calls print() at line(s) {lines}. Seeders log: "
        "use the module's `logger = logging.getLogger(__name__)` (info for progress, "
        "warning for skips)."
    )


@pytest.mark.parametrize("dept", DEPARTMENTS)
def test_every_department_seeder_has_a_module_logger(dept):
    """The other half of the tripwire: prints removed AND a logger left behind.

    Deleting the print calls alone would pass the test above while making the seed
    silent, which is a worse outcome than the noise it replaced.
    """
    tree = ast.parse((BACKEND / "app" / dept / "seed.py").read_text(encoding="utf-8"))
    bound = {target.id
             for node in tree.body if isinstance(node, ast.Assign)
             for target in node.targets if isinstance(target, ast.Name)}
    assert "logger" in bound, f"app/{dept}/seed.py has no module-level `logger`"

    logged = {node.func.attr for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
              and isinstance(node.func.value, ast.Name) and node.func.value.id == "logger"}
    assert logged, f"app/{dept}/seed.py binds a logger it never calls - the seed went silent"
    assert logged <= {"debug", "info", "warning", "error", "exception", "critical"}, logged


# ── the surface app.core.seed must keep, whatever shape it takes ─────────────

def test_core_seed_exposes_every_externally_imported_name():
    """Each name below is imported from `app.core.seed` by real code, not by this
    test. A split that forgets one breaks its caller at import time.

        seed_database         app/main.py, scripts/seed_master.py
        seed_connectors       tests/test_neural_map.py
        seed_departments      tests/test_department_contract.py,
                              tests/test_s6_department_registry.py
        top_up_new_entities   tests/test_ten_department_crosscut.py
        NOW                   assigned by the two department tests above
    """
    from app.core import seed

    for name in ("seed_database", "seed_connectors", "seed_departments",
                 "top_up_new_entities", "NOW"):
        assert hasattr(seed, name), f"app.core.seed lost `{name}`"


def test_now_is_readable_where_seed_departments_reads_it():
    """The M2.3 blocker, as an executable fact.

    Assigning `app.core.seed.NOW` from outside must reach the builder. This passes
    trivially today because both live in one module; it is the FIRST thing a
    package split breaks, and it fails here loudly instead of inside an unrelated
    department test.
    """
    from datetime import datetime, timezone

    from app.core import seed

    seed.NOW = datetime.now(timezone.utc)
    try:
        departments = seed.seed_departments()
    except TypeError as exc:  # NOW still None where the builder reads it
        pytest.fail(
            f"seed_departments() could not see the NOW assigned above ({exc}). It is "
            "no longer reading the same global the external callers write. See this "
            "module's docstring: that is the split, and it breaks two other test files."
        )

    assert departments, "seed_departments() returned nothing"
    assert all(d.deployed_at is not None for d in departments)
