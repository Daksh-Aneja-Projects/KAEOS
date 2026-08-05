"""Every control's evidence must point at something that actually exists.

The audit-readiness report (`build_controls_report`) is described in its own
output as "the evidence you take INTO that audit". If a control claims
IMPLEMENTED while citing a path that was renamed, deleted, or was simply the
wrong file, the report launders a broken claim as proof - the same failure
class as a fabricated metric, but on a regulated control.

Nothing validated these paths before, so AU-2 spent a release citing
`governance_engine.py` (ABAC, no hash chain, never called) for the hash-chained
provenance control that `quantum_ledger.py` actually implements. This test
makes that class of rot fail the build instead of reaching an auditor.
"""
from pathlib import Path

import pytest

from app.services.compliance_controls import _CONTROLS, ControlStatus

# tests/ -> backend/ : evidence paths are written relative to the backend root.
BACKEND_ROOT = Path(__file__).resolve().parent.parent


def _evidence_pairs():
    return [(c.id, p) for c in _CONTROLS for p in c.evidence]


@pytest.mark.parametrize("control_id,evidence_path", _evidence_pairs())
def test_evidence_path_exists(control_id, evidence_path):
    """A cited file or directory must resolve inside the repo."""
    assert (BACKEND_ROOT / evidence_path).exists(), (
        f"Control {control_id} cites evidence '{evidence_path}', which does not "
        f"exist. Repoint it at the code/test that actually proves the control, "
        f"or drop the citation - never leave a control citing a dead path."
    )


def test_implemented_controls_cite_evidence():
    """IMPLEMENTED is a claim; it needs at least one artifact behind it."""
    missing = [c.id for c in _CONTROLS
               if c.status == ControlStatus.IMPLEMENTED and not c.evidence]
    assert not missing, f"IMPLEMENTED controls with no evidence at all: {missing}"


def test_external_controls_claim_nothing():
    """EXTERNAL/OPERATIONAL controls must not be reported as satisfied."""
    for c in _CONTROLS:
        if c.status in (ControlStatus.EXTERNAL, ControlStatus.OPERATIONAL):
            assert c.status != ControlStatus.IMPLEMENTED
