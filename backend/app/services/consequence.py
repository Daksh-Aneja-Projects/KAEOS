"""Single source of truth for high-consequence (always-HITL) detection.

A high-consequence action (payment, termination, contract execution, external
send, data deletion) ALWAYS routes to a human at Gate 3, regardless of
confidence. Both enforcement sites (app/agents/runtime.py Gate 3 and the
/skills/{id}/execute route) call is_high_consequence(); the previous inline
substring-blob implementations were duplicated and could drift apart.

Detection order:
  1. The explicit ``always_hitl`` field on the Skill - authoritative. An
     explicitly flagged skill can NEVER be de-escalated by naming or tags.
  2. Tag/name inference over compliance tags, tags, department and skill_id
     (HIGH_CONSEQUENCE_TAGS) - a fallback that can only ESCALATE, kept so
     legacy skills without the explicit flag stay safe.
"""
from typing import Any

from app.core.config import get_settings

# Field-name tokens that mark an actuation payload as money-moving. Checked
# against a finance/accounting UPDATE's payload keys so a wire/amount/balance
# change forces a human even when the skill carries no matching tag.
_MONEY_TOKENS = ("amount", "total", "balance", "payment", "wire", "transfer",
                 "debit", "credit", "price", "cost", "value", "usd", "invoice",
                 "payout", "disburse", "refund", "sum")


def _moves_money(payload: Any) -> bool:
    """Heuristic: does this finance actuation payload move money?

    Checks field NAMES for monetary tokens. Fail-closed bias: an empty or opaque
    payload on a finance write is treated as money-moving, so a missing or renamed
    field can never buy autonomous execution of a financial mutation.
    """
    # ponytail: name-token heuristic; swap for a typed payload schema if actuation
    # payloads ever carry declared field semantics.
    if not isinstance(payload, dict) or not payload:
        return True
    keys = " ".join(str(k).lower() for k in payload.keys())
    return any(tok in keys for tok in _MONEY_TOKENS)


def is_high_consequence_api_write(operation: str, payload: Any) -> bool:
    """Consequence rule for RAW API writes (/actuation/execute and /reverse).

    A raw API write carries no skill, no department, and no compliance tags,
    so the department-aware rule 1b below cannot see it. At this boundary the
    posture is strictest: DELETE always escalates, and a CREATE/UPDATE whose
    payload is money-shaped escalates too (fail-closed on an empty/opaque
    payload, same bias as _moves_money) — a wire, payout, or balance change
    issued straight at the API must never apply on one person's authority.
    """
    op = str(operation or "").strip().upper()
    if op == "DELETE":
        return True
    return op in ("CREATE", "UPDATE") and _moves_money(payload)


def is_high_consequence(skill: Any) -> bool:
    """True when this skill must always route to a human, regardless of
    confidence. Accepts a Skill ORM object or the executor's skill dict."""
    if skill is None:
        return False
    if isinstance(skill, dict):
        def get(key, default=None):
            return skill.get(key, default)
    else:
        def get(key, default=None):
            return getattr(skill, key, default)

    # 1. Explicit flag: authoritative, never de-escalated.
    if bool(get("always_hitl", False)):
        return True

    # 1b. Actuation intent: an irreversible/money-moving WRITE is high-consequence
    # regardless of naming. Gate 5b performs the actual write, but the confidence
    # gate (Gate 3) only forces HITL when THIS returns True - so a skill carrying a
    # DELETE actuation (or a finance/accounting money-moving UPDATE) with no
    # always_hitl flag and no matching tag would otherwise execute autonomously.
    # Escalate-only, like the tag inference below.
    actuation = get("actuation")
    if isinstance(actuation, dict):
        op = str(actuation.get("operation") or "").strip().upper()
        if op == "DELETE":
            return True
        if op == "UPDATE":
            dept = str(get("department") or "").lower()
            if dept in ("finance", "accounting") and _moves_money(actuation.get("payload")):
                return True

    # 2. Naming-convention inference: escalate-only fallback.
    parts = list(get("compliance_tags") or []) + list(get("tags") or [])
    for key in ("department", "skill_id"):
        val = get(key)
        if val:
            parts.append(str(val))
    blob = " ".join(str(x).lower() for x in parts)
    return any(t in blob for t in get_settings().HIGH_CONSEQUENCE_TAGS)


if __name__ == "__main__":  # tiny self-check of the actuation-consequence branch
    # A DELETE actuation forces HITL even with no flag/tag.
    assert is_high_consequence({"actuation": {"operation": "DELETE"}})
    # A finance money-moving UPDATE forces HITL.
    assert is_high_consequence({"department": "finance", "actuation": {
        "operation": "UPDATE", "payload": {"amount": 100}}})
    # An opaque finance UPDATE is treated as money-moving (fail-closed).
    assert is_high_consequence({"department": "finance", "actuation": {
        "operation": "UPDATE", "payload": {}}})
    # A non-finance, non-money UPDATE with no risky naming does NOT escalate here.
    assert not is_high_consequence({"department": "support", "skill_id": "reply_ack",
                                    "actuation": {"operation": "UPDATE",
                                                  "payload": {"note": "ok"}}})
    # A finance UPDATE touching only a non-money field does NOT escalate on money.
    assert not is_high_consequence({"department": "finance", "skill_id": "memo_update",
                                    "actuation": {"operation": "UPDATE",
                                                  "payload": {"memo": "x"}}})
    # The explicit flag still wins.
    assert is_high_consequence({"always_hitl": True})
    # Raw API writes: DELETE always; money-shaped payloads on CREATE/UPDATE;
    # empty payload fail-closed; plain non-money UPDATE passes.
    assert is_high_consequence_api_write("DELETE", {"note": "x"})
    assert is_high_consequence_api_write("UPDATE", {"payout_usd": 5000})
    assert is_high_consequence_api_write("CREATE", {})
    assert not is_high_consequence_api_write("UPDATE", {"note": "ok"})
    print("consequence actuation self-check passed")
