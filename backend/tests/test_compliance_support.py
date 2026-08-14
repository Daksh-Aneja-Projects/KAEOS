"""Support department deterministic checkers: PII redaction (regex + Luhn),
two-party call-recording consent, and SLA breach. No LLM, no DB - pure."""
from app.compliance import CheckStatus, run_checks


def _status(result, framework):
    return next(r["status"] for r in result["results"] if r["framework"] == framework)


def _findings(result, framework):
    return next(r["findings"] for r in result["results"] if r["framework"] == framework)


# --- PII_REDACTION ----------------------------------------------------------

def test_pii_blocks_on_credit_card():
    # 4111 1111 1111 1111 is the canonical Luhn-valid Visa test PAN.
    ctx = {"outbound_text": "Sure, I can refund the card 4111 1111 1111 1111 today."}
    assert _status(run_checks(["PII_REDACTION"], ctx), "PII_REDACTION") == CheckStatus.BLOCK.value


def test_pii_blocks_on_ssn_and_api_key():
    ssn = {"message": "Your file lists SSN 123-45-6789 as verified."}
    assert _status(run_checks(["PII_REDACTION"], ssn), "PII_REDACTION") == CheckStatus.BLOCK.value
    key = {"reply": "Set the header to AKIAIOSFODNN7EXAMPLE to authenticate."}
    assert _status(run_checks(["PII_REDACTION"], key), "PII_REDACTION") == CheckStatus.BLOCK.value


def test_pii_passes_on_redacted_text():
    # Masked PAN and masked SSN carry no Luhn-valid / pattern-matching value.
    ctx = {"outbound_text": "We refunded the card ending ****-****-****-1111 (SSN on file XXX-XX-6789)."}
    assert _status(run_checks(["PII_REDACTION"], ctx), "PII_REDACTION") == CheckStatus.PASS.value


def test_pii_not_applicable_without_text():
    assert _status(run_checks(["PII_REDACTION"], {"foo": 1}),
                   "PII_REDACTION") == CheckStatus.NOT_APPLICABLE.value


def test_pii_finding_does_not_echo_the_secret():
    ctx = {"outbound_text": "card 4111 1111 1111 1111"}
    msg = " ".join(f["message"] for f in _findings(run_checks(["PII_REDACTION"], ctx), "PII_REDACTION"))
    assert "4111" not in msg  # the audit trail must not re-leak the PAN


def test_pii_blocks_on_pan_glued_to_adjacent_digits():
    # Finding 1: PAN embedded in a longer digit run - the full 18-digit run is
    # NOT Luhn-valid, so a whole-run-only test would false-PASS. Sliding catches
    # the embedded 4111-... Visa (no card keyword present).
    ctx = {"outbound_text": "ref 994111111111111111 end"}
    assert _status(run_checks(["PII_REDACTION"], ctx), "PII_REDACTION") == CheckStatus.BLOCK.value


def test_pii_blocks_on_unformatted_ssn():
    # Finding 2: bare 9-digit SSN with no separators must be caught.
    ctx = {"message": "Your file lists SSN 123456789 as verified."}
    assert _status(run_checks(["PII_REDACTION"], ctx), "PII_REDACTION") == CheckStatus.BLOCK.value


def test_pii_passes_on_imei():
    # Finding 4: a Luhn-valid 15-digit IMEI (no card IIN prefix, no card keyword)
    # must not be blocked as a PAN.
    ctx = {"outbound_text": "Device IMEI 890154203237514 was swapped."}
    assert _status(run_checks(["PII_REDACTION"], ctx), "PII_REDACTION") == CheckStatus.PASS.value


# --- CALL_RECORDING_CONSENT -------------------------------------------------

def test_recording_blocks_two_party_without_consent():
    ctx = {"call_recording": {"recording": True, "state": "CA", "consent_captured": False}}
    assert _status(run_checks(["CALL_RECORDING_CONSENT"], ctx),
                   "CALL_RECORDING_CONSENT") == CheckStatus.BLOCK.value


def test_recording_passes_two_party_with_consent():
    ctx = {"call_recording": {"recording": True, "state": "CA", "consent_captured": True}}
    assert _status(run_checks(["CALL_RECORDING_CONSENT"], ctx),
                   "CALL_RECORDING_CONSENT") == CheckStatus.PASS.value


def test_recording_passes_one_party_state():
    ctx = {"call_recording": {"recording": True, "state": "NY", "consent_captured": False}}
    assert _status(run_checks(["CALL_RECORDING_CONSENT"], ctx),
                   "CALL_RECORDING_CONSENT") == CheckStatus.PASS.value


def test_recording_not_applicable_when_not_recording():
    assert _status(run_checks(["CALL_RECORDING_CONSENT"], {}),
                   "CALL_RECORDING_CONSENT") == CheckStatus.NOT_APPLICABLE.value


def test_recording_blocks_connecticut_all_party():
    # Finding 3: Connecticut (Conn. Gen. Stat. 52-570d) is all-party.
    ctx = {"call_recording": {"recording": True, "state": "CT", "consent_captured": False}}
    assert _status(run_checks(["CALL_RECORDING_CONSENT"], ctx),
                   "CALL_RECORDING_CONSENT") == CheckStatus.BLOCK.value


def test_recording_two_party_false_cannot_loosen_all_party_state():
    # Finding 5: an explicit two_party=False must not downgrade an all-party
    # jurisdiction to one-party - it may only tighten, never loosen.
    ctx = {"call_recording": {"recording": True, "state": "CA",
                              "two_party": False, "consent_captured": False}}
    assert _status(run_checks(["CALL_RECORDING_CONSENT"], ctx),
                   "CALL_RECORDING_CONSENT") == CheckStatus.BLOCK.value


def test_recording_two_party_true_tightens_one_party_state():
    # The flag may still tighten: force all-party in a one-party state.
    ctx = {"call_recording": {"recording": True, "state": "NY",
                              "two_party": True, "consent_captured": False}}
    assert _status(run_checks(["CALL_RECORDING_CONSENT"], ctx),
                   "CALL_RECORDING_CONSENT") == CheckStatus.BLOCK.value


def test_recording_advisory_when_jurisdiction_unknown():
    ctx = {"call_recording": {"recording": True, "consent_captured": False}}
    assert _status(run_checks(["CALL_RECORDING_CONSENT"], ctx),
                   "CALL_RECORDING_CONSENT") == CheckStatus.ADVISORY.value


# --- SLA_BREACH -------------------------------------------------------------

def test_sla_advisory_on_breach():
    # High priority = 8h SLA; 30h open is a breach -> advisory (never blocks).
    ctx = {"ticket": {"priority": "high", "age_hours": 30}}
    res = run_checks(["SLA_BREACH"], ctx)
    assert _status(res, "SLA_BREACH") == CheckStatus.ADVISORY.value
    assert res["verified"] is True  # advisory does not fail the gate


def test_sla_pass_within_window():
    ctx = {"ticket": {"priority": "high", "age_hours": 3}}
    assert _status(run_checks(["SLA_BREACH"], ctx), "SLA_BREACH") == CheckStatus.PASS.value


def test_sla_breach_from_timestamps():
    ctx = {"ticket": {"priority": "urgent", "opened_at": "2026-03-02T09:00:00",
                      "now": "2026-03-02T15:00:00"}}  # 6h open vs 4h urgent SLA
    assert _status(run_checks(["SLA_BREACH"], ctx), "SLA_BREACH") == CheckStatus.ADVISORY.value


def test_sla_not_applicable_without_ticket():
    assert _status(run_checks(["SLA_BREACH"], {}),
                   "SLA_BREACH") == CheckStatus.NOT_APPLICABLE.value


def test_sla_advisory_on_unknown_priority():
    ctx = {"ticket": {"priority": "cosmic", "age_hours": 5}}
    assert _status(run_checks(["SLA_BREACH"], ctx), "SLA_BREACH") == CheckStatus.ADVISORY.value
