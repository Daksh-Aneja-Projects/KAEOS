"""S6 M8.4 — one canonical department roster.

`app.core.domain_seed.DEPARTMENT_SLUGS` is the single backend roster. The sweep
behind this file found NO second copy of it: every ten-slug lookalike in the
backend binds per-department data to its slug (an analytics callable, a model
path, a router object, a connector category, a seeded ORM row), so none of them
can be derived from the roster. What they CAN drift on is coverage - a new
department that never reaches one of those sites - so each one is pinned here.

Two lookalikes are deliberately different and are pinned as different, so a
future "consolidation" that folds them into the roster fails loudly instead of
quietly changing behaviour:

  * event_mesh._CANON        - inbound SIGNAL labels, 11 entries incl. "marketing"
  * missions.planner._DEPT_ORDER - execution PRIORITY order, same 11 entries

What the sweep did find was one genuine duplicate: three partial, drifted copies
of the Skill.department -> Department.slug normalization. Those are now one map.
"""
import inspect

from app.core.domain_seed import DEPARTMENT_SLUGS, _DEPT_SLUG_MAP


# The tripwire literal. Editing DEPARTMENT_SLUGS must be a deliberate act that
# also edits this line - not a side effect of some other change.
TEN = {
    "hr", "finance", "legal", "sales", "support",
    "operations", "engineering", "healthcare", "procurement", "lending",
}


def test_canonical_roster_is_exactly_the_ten_known_slugs():
    assert set(DEPARTMENT_SLUGS) == TEN
    assert len(DEPARTMENT_SLUGS) == 10, "no duplicates in the canonical order"


# ── converged: one Skill.department -> Department.slug map ───────────────────

def test_workforce_analytics_reuses_the_canonical_alias_map():
    """Was a private 9-entry copy that knew none of the three regulated
    departments; its identity fallback leaked the unmapped labels into the ROI
    dashboard as phantom department slugs."""
    from app.workforce.api.analytics import _DEPT_ALIAS
    assert _DEPT_ALIAS is _DEPT_SLUG_MAP


def test_wargame_canon_reuses_the_canonical_alias_map():
    """Was a 4-entry inline dict inside _canon()."""
    from app.services import wargame
    assert "_DEPT_SLUG_MAP" in inspect.getsource(wargame._canon)
    assert wargame._canon("it ops") == "engineering"
    assert wargame._canon("human_resources") == "hr"
    assert wargame._canon("healthcare") == "healthcare"
    assert wargame._canon(None) == "general", "unknown input still degrades, not raises"


def test_alias_map_absorbed_every_label_its_three_copies_knew():
    """The union the three copies collectively covered. Any of these missing
    means a real Skill.department value stops being attributed."""
    for label, slug in (
        ("customer_support", "support"), ("customer success", "support"),
        ("human resources", "hr"), ("human_resources", "hr"),
        ("it ops", "engineering"), ("platform", "engineering"), ("eng", "engineering"),
        ("ops", "operations"),
    ):
        assert _DEPT_SLUG_MAP[label] == slug, label


def test_every_roster_slug_normalizes_to_itself():
    """A department slug must never normalize to a DIFFERENT department -
    procurement was once aliased into operations and lost its identity."""
    for slug in DEPARTMENT_SLUGS:
        assert _DEPT_SLUG_MAP[slug] == slug


# ── refuted: deliberately not the roster ─────────────────────────────────────

def test_event_mesh_canon_is_signal_labels_not_the_roster():
    from app.services.event_mesh import _CANON
    assert "marketing" in _CANON, "signal labels carry a label with no department"
    assert set(_CANON) - TEN == {"marketing"}
    assert TEN <= set(_CANON), "every real department must still be a signal label"


def test_planner_dept_order_is_a_priority_order_not_the_roster():
    from app.services.missions.planner import _DEPT_ORDER, _HIGH_CONSEQUENCE
    assert set(_DEPT_ORDER) - TEN == {"marketing"}
    assert TEN <= set(_DEPT_ORDER)
    # The order is the payload: regulated departments plan before the rest.
    assert _DEPT_ORDER.index("legal") < _DEPT_ORDER.index("sales")
    assert _DEPT_ORDER != DEPARTMENT_SLUGS
    assert _HIGH_CONSEQUENCE < TEN, "a meaningful subset, not the whole roster"


# ── coverage: sites that bind per-department data must still span the roster ──

def test_org_pulse_aggregates_every_department():
    from app.api.routes.org_pulse import _DOMAIN_ANALYTICS
    assert {slug for slug, _ in _DOMAIN_ANALYTICS} == TEN
    assert all(callable(fn) for _, fn in _DOMAIN_ANALYTICS)


def test_seeded_department_rows_are_exactly_the_roster():
    from datetime import datetime, timezone

    from app.core import seed as core_seed
    core_seed.NOW = datetime.now(timezone.utc)
    assert {d.slug for d in core_seed.seed_departments()} == TEN


def test_every_department_router_is_department_gated_at_its_mount():
    """`require_department(slug)` on the router mount is the single point of
    department-scoped RBAC. A department that ships without one is an open
    surface, so the roster and the gated mounts must match exactly."""
    from app.main import app

    gated = set()
    for route in app.routes:
        dependant = getattr(route, "dependant", None)
        for dep in getattr(dependant, "dependencies", None) or []:
            call = getattr(dep, "call", None)
            code = getattr(call, "__code__", None)
            if code is None:
                continue
            for name, cell in zip(code.co_freevars, call.__closure__ or ()):
                if name == "department":
                    gated.add(cell.cell_contents)

    assert gated == TEN
