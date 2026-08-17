"""
COMPLIANCE-INVARIANT 'neuter-the-field' pack.

Complements tests/test_statutory_invariants.py. Its job is to prove each
statutory control is NOT silently removable: a violation must BLOCK, and when the
field that ENFORCES the control is neutered (dropped / blanked / renamed), the
control must still fail closed — never silently read as satisfied.

``run_checks(tags, ctx)['verified'] is False`` means the pipeline blocked. The
registry itself fails closed (an unbacked tag or a raising checker → blocking),
so these tests exercise the checkers' own field-level fail-closed contracts.

Some checkers are legitimately NOT_APPLICABLE when their input is absent (there
is nothing to evaluate). For those the invariant is narrower and asserted
explicitly: a KNOWN violation is caught when the data IS present, and the
absent-input semantics are pinned so a future change that turns "missing field"
into a silent PASS of a real violation breaks this test.
"""
import pytest

# Import the checker modules so their @register decorators populate the registry
# even if this test runs in isolation (no app.main import).
import app.compliance.checkers.finance   # noqa: F401  (SOX)
import app.compliance.checkers.lending   # noqa: F401  (ECOA, FDCPA, LENDING_SOD)
import app.compliance.checkers.support   # noqa: F401  (PII_REDACTION)
from app.compliance.registry import run_checks


def _verified(tags, ctx) -> bool:
    return run_checks(tags, ctx)["verified"]


# ── SOX four-eyes: the money control ─────────────────────────────────────────
# Enforcing fields: has_human_approver + a distinct attributable maker/approver.
SOX_CASES = [
    # (id, context, expect_verified)
    ("financial_no_approver_blocks",
     {"is_financial": True, "has_human_approver": False}, False),
    # Neuter the approver field entirely: default is_financial True + no approver
    # must STILL block (a missing approval field cannot buy a pass).
    ("neuter_approver_field_still_blocks", {}, False),
    # Approved but the maker identity is neutered → four-eyes unverifiable → block.
    ("neuter_maker_unverifiable_blocks",
     {"is_financial": True, "has_human_approver": "cfo@corp"}, False),
    # A constant/non-attributable approver cannot satisfy SoD.
    ("constant_email_approver_blocks",
     {"is_financial": True, "has_human_approver": True,
      "maker": "clerk@corp", "approver": "email-approver"}, False),
    # Maker == approver (self-approval) blocks.
    ("self_approval_blocks",
     {"is_financial": True, "has_human_approver": True,
      "maker": "cfo@corp", "approver": "cfo@corp"}, False),
    # Positive control: distinct attributable maker + approver PASSES (proves the
    # checker discriminates and the blocks above are real, not blanket-deny).
    ("distinct_maker_approver_passes",
     {"is_financial": True, "has_human_approver": "cfo@corp",
      "maker": "clerk@corp", "approver": "cfo@corp"}, True),
]


@pytest.mark.parametrize("cid,ctx,expect", SOX_CASES, ids=[c[0] for c in SOX_CASES])
def test_sox_four_eyes_invariant(cid, ctx, expect):
    assert _verified(["SOX"], ctx) is expect


# ── Lending segregation of duties ────────────────────────────────────────────
# Enforcing field: lending_sod{policy_maker, underwriter}.
LENDING_SOD_CASES = [
    ("maker_is_underwriter_blocks",
     {"lending_sod": {"policy_maker": "admin@bank", "underwriter": "admin@bank"}}, False),
    # Neuter the underwriter identity → four-eyes unverifiable → block (fail-closed).
    ("neuter_underwriter_blocks",
     {"lending_sod": {"policy_maker": "admin@bank"}}, False),
    # Distinct attributable maker/underwriter passes.
    ("distinct_passes",
     {"lending_sod": {"policy_maker": "policy@bank", "underwriter": "uw@bank"}}, True),
    # Documented absent-input semantics: no recorded policy maker (default policy)
    # → NOT_APPLICABLE → verified (nothing to segregate). Pinned so a change that
    # turns "no maker" into a silent pass of a real maker==uw case is caught above.
    ("no_policy_maker_not_applicable",
     {"lending_sod": {"underwriter": "uw@bank"}}, True),
]


@pytest.mark.parametrize("cid,ctx,expect", LENDING_SOD_CASES, ids=[c[0] for c in LENDING_SOD_CASES])
def test_lending_sod_invariant(cid, ctx, expect):
    assert _verified(["LENDING_SOD"], ctx) is expect


# ── ECOA adverse-action 30-day clock ─────────────────────────────────────────
# Enforcing field: adverse_action.notice_days. A KNOWN late notice must block;
# the boundary must pass. (Absent notice_days is NOT_APPLICABLE for timing — the
# underwriting service always supplies it, so omission is not an escape hatch it
# can reach; that path is covered by test_statutory_invariants.)
def _ecoa_ctx(notice_days):
    # A specific principal reason (>=8 chars, non-generic) so the ONLY thing that
    # varies the verdict is the notice timing — isolating the 30-day control.
    return {"decision": "DENY",
            "adverse_action": {"reasons": ["insufficient_income"], "notice_days": notice_days,
                               "prohibited_basis_used": False}}


@pytest.mark.parametrize("notice_days,expect_verified", [
    (45, False),   # late notice blocks
    (31, False),   # just over the line blocks
    (30, True),    # boundary passes
])
def test_ecoa_notice_window_invariant(notice_days, expect_verified):
    assert _verified(["ECOA"], _ecoa_ctx(notice_days)) is expect_verified


# ── FDCPA Reg F 7-in-7 call-frequency cap ────────────────────────────────────
# Enforcing field: collection.phone_contacts_last_7d.
@pytest.mark.parametrize("contacts,expect_verified", [
    (7, False),   # an 8th call in the window blocks
    (8, False),
    (6, True),    # under the cap passes (nothing else in this minimal context blocks)
])
def test_fdcpa_call_cap_invariant(contacts, expect_verified):
    ctx = {"collection": {"phone_contacts_last_7d": contacts}}
    assert _verified(["FDCPA"], ctx) is expect_verified


# ── Support PII redaction on outbound customer content ───────────────────────
# A PAN in recognized content must block; clean content passes.
def test_pii_redaction_pan_blocks():
    assert _verified(["PII_REDACTION"], {"ticket_text": "refund my card 4111 1111 1111 1111"}) is False


def test_pii_redaction_clean_passes():
    assert _verified(["PII_REDACTION"], {"ticket_text": "my order never arrived"}) is True


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
