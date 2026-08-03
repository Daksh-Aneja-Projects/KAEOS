"""Regression: hours-saved is never fabricated, and never a bare 0.

`hours_saved` (and any cost derived from it) needs two tenant inputs KAEOS
cannot observe: how long the task took a human before automation, and that
human's loaded hourly cost. It was once derived as `tasks * 0.5` hours and then
multiplied by a hardcoded rate - two fabrications stacked into a confident ROI
figure with nothing behind it.

/billing was fixed to report null-with-note, and a test locked it there. The
workforce surfaces were NOT covered, so they kept the heuristic and drifted away
from the documented contract. This test covers the whole contract in one place:

  1. the producer must not invent the number,
  2. absent means null-with-note, never 0.0 ("measured, saved nothing"),
  3. a real measured 0 is still reportable,
  4. cost is never derived from hours that are not themselves real,
  5. a tenant tracking cost but not hours keeps its real cost figure.
"""
import inspect

from app.workforce.models.core import (
    HOURS_SAVED_BASIS_TENANT,
    HOURS_SAVED_BASIS_UNSET,
    HOURS_SAVED_NOTE,
    hours_saved_payload,
)

RATE = 85.0


# ── The contract itself ───────────────────────────────────────────────────────

def test_absent_hours_are_null_with_a_note_not_zero():
    """The whole point: absent must not render as a measured zero."""
    p = hours_saved_payload(None, RATE)
    assert p["hours_saved"] is None, "absent hours must be null, never 0"
    assert p["cost_saved"] is None, "no hours means no cost to derive"
    assert p["hours_saved_basis"] == HOURS_SAVED_BASIS_UNSET
    assert p["hours_saved_note"] == HOURS_SAVED_NOTE


def test_zero_stored_hours_are_treated_as_no_baseline():
    """0.0 is the column default, so it means 'unset', not 'measured zero'."""
    p = hours_saved_payload(0.0, RATE)
    assert p["hours_saved"] is None
    assert p["cost_saved"] is None
    assert p["hours_saved_basis"] == HOURS_SAVED_BASIS_UNSET


def test_tenant_supplied_hours_are_reported_and_cost_derived():
    p = hours_saved_payload(120.0, RATE)
    assert p["hours_saved"] == 120.0
    assert p["cost_saved"] == round(120.0 * RATE, 2)
    assert p["hours_saved_basis"] == HOURS_SAVED_BASIS_TENANT
    assert p["hours_saved_note"] is None, "a real figure needs no disclaimer"


def test_cost_is_never_derived_without_a_rate():
    p = hours_saved_payload(120.0, None)
    assert p["hours_saved"] == 120.0
    assert p["cost_saved"] is None


def test_tenant_cost_without_hours_is_kept():
    """A tenant tracking cost directly must not lose it because hours are unset."""
    p = hours_saved_payload(None, RATE, 9_500.0)
    assert p["cost_saved"] == 9_500.0
    assert p["hours_saved"] is None, "hours were never supplied"
    assert p["hours_saved_basis"] == HOURS_SAVED_BASIS_TENANT
    assert p["hours_saved_note"] == HOURS_SAVED_NOTE, (
        "cost is real but hours are not - the reader still needs to know why"
    )


def test_tenant_cost_wins_over_the_derived_figure():
    """An explicitly tracked cost beats one inferred from hours x rate."""
    p = hours_saved_payload(100.0, RATE, 1_234.0)
    assert p["cost_saved"] == 1_234.0, "a stored cost must not be overwritten"


# ── The producer must not reintroduce the heuristic ───────────────────────────

def test_rollup_does_not_derive_hours_saved():
    """`rollup_department_metrics` computed `tasks * 0.5`. It must never again.

    Guards the root cause: every reader below is only honest because nothing
    writes a fabricated value into the column in the first place.
    """
    from app.core.domain_seed import rollup_department_metrics

    src = inspect.getsource(rollup_department_metrics)
    assignments = [
        ln for ln in src.splitlines()
        if "hours_saved_total" in ln and "=" in ln and not ln.strip().startswith("#")
    ]
    assert not assignments, (
        "rollup_department_metrics must not assign hours_saved_total; it needs a "
        f"tenant baseline. Offending line(s): {assignments}"
    )


# ── Every reader routes through the shared contract ───────────────────────────

def test_all_hours_saved_surfaces_use_the_shared_helper():
    """No endpoint may hand-roll its own hours-saved block again.

    The original defect was per-endpoint copies drifting apart: /billing told
    the truth while the workforce surfaces quietly kept the heuristic. Any
    module that emits an hours/cost-saved figure must import the shared helper.
    """
    from pathlib import Path

    import app.workforce as workforce_pkg

    root = Path(workforce_pkg.__file__).parent
    offenders = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        emits = '"hours_saved' in text or '"total_hours_saved"' in text
        if not emits:
            continue
        # models/core.py defines the contract; it need not import itself.
        if path.name == "core.py" and path.parent.name == "models":
            continue
        if "hours_saved_payload" not in text:
            offenders.append(str(path.relative_to(root)))

    assert not offenders, (
        "these workforce modules emit hours-saved without the shared "
        f"hours_saved_payload contract: {offenders}"
    )
