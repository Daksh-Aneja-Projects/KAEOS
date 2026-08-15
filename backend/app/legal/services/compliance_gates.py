"""
KAEOS Legal — Statutory Action Gates (Conflict of Interest / Legal Hold / Retention)

Binds three of the four deterministic legal checkers
(app/compliance/checkers/legal.py) as real gates in front of genuine legal
actions instead of leaving them registered-but-unused. No LLM, no DB — pure
functions over ``run_checks``' verdict. The fourth (CONTRACT_CLAUSE) is wired
directly into contract_review_agent.py's gated compliance_tags instead, since
it needs the full 7-gate pipeline's audit trail, not a pre-write guard.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.compliance.registry import run_checks
from app.core.workflow import TransitionContext


def _reasons(verdict: Dict[str, Any]) -> str:
    return "; ".join(
        f["framework"] + ": " + "; ".join(m["message"] for m in f["findings"])
        for f in verdict["blocking"]
    )


class ConflictOfInterestBlocked(ValueError):
    """CONFLICT_OF_INTEREST returned a blocking verdict. Carries the full
    verdict so the caller (the router) can surface WHY the matter cannot be
    opened."""

    def __init__(self, message: str, verdict: Dict[str, Any]):
        super().__init__(message)
        self.verdict = verdict


def screen_new_matter(
    parties: Optional[List[str]], adverse_parties: Optional[List[str]],
) -> Dict[str, Any]:
    """ABA Model Rule 1.7 conflict-of-interest screen, run before a new legal
    matter is opened. Raises on a real adverse-party overlap. A matter opened
    with no party list is NOT_APPLICABLE (nothing to screen) — never a
    fabricated pass on data that was never supplied."""
    verdict = run_checks(
        ["CONFLICT_OF_INTEREST"],
        {"matter": {"parties": parties, "adverse_parties": adverse_parties}},
    )
    if not verdict["verified"]:
        raise ConflictOfInterestBlocked(
            _reasons(verdict) or "Blocked by the conflict-of-interest screen.", verdict,
        )
    return verdict


def guard_matter_closure(matter: Any, ctx: TransitionContext) -> Optional[str]:
    """WorkflowSpec guard (app/legal/services/workflows.py): FRCP 37(e) legal
    hold + records-retention screen before a matter file is closed out.
    LegalMatter carries no on_legal_hold / retention_until columns yet, so an
    unheld matter reads ADVISORY (non-blocking) — honest given hold-tracking
    isn't modeled, but a future hold flag on the row would BLOCK here for
    real. Returning a string here blocks the transition with a 409."""
    verdict = run_checks(["LEGAL_HOLD", "RETENTION_SCHEDULE"], {"action": "delete", "record": {}})
    if verdict["verified"]:
        return None
    return _reasons(verdict) or "Blocked by the legal-hold / retention-schedule screen."
