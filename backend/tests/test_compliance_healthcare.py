"""Healthcare compliance spine: deterministic HIPAA + 42 CFR Part 2 checkers.
Pure functions, no LLM / DB. Covers a PASS, a BLOCK, and the
NOT_APPLICABLE/ADVISORY branch for each checker."""
from app.compliance import CheckStatus, run_checks
from app.compliance.registry import list_frameworks


def _status(result, framework):
    return next(r["status"] for r in result["results"] if r["framework"] == framework)


def test_healthcare_frameworks_registered():
    tags = {f["framework"] for f in list_frameworks()}
    assert {"HIPAA_MINIMUM_NECESSARY", "HIPAA_AUTHORIZATION",
            "HIPAA_DEIDENTIFICATION", "PART2"} <= tags


def test_minimum_necessary_blocks_on_excess_fields():
    # Payment disclosure that also ships the SSN exceeds minimum necessary.
    over = {"phi_disclosure": {"purpose": "payment",
                               "fields": ["name", "member_id", "billing_amount", "ssn"]}}
    assert _status(run_checks(["HIPAA_MINIMUM_NECESSARY"], over),
                   "HIPAA_MINIMUM_NECESSARY") == CheckStatus.BLOCK.value

    ok = {"phi_disclosure": {"purpose": "payment",
                             "fields": ["name", "member_id", "billing_amount"]}}
    assert _status(run_checks(["HIPAA_MINIMUM_NECESSARY"], ok),
                   "HIPAA_MINIMUM_NECESSARY") == CheckStatus.PASS.value

    # Treatment is exempt from minimum-necessary; no disclosure at all -> N/A.
    treat = {"phi_disclosure": {"purpose": "treatment", "fields": ["name", "ssn"]}}
    assert _status(run_checks(["HIPAA_MINIMUM_NECESSARY"], treat),
                   "HIPAA_MINIMUM_NECESSARY") == CheckStatus.NOT_APPLICABLE.value
    assert _status(run_checks(["HIPAA_MINIMUM_NECESSARY"], {}),
                   "HIPAA_MINIMUM_NECESSARY") == CheckStatus.NOT_APPLICABLE.value
    # Unknown purpose cannot be verified -> ADVISORY, not a silent PASS.
    unknown = {"phi_disclosure": {"purpose": "data_broker_sale", "fields": ["name"]}}
    assert _status(run_checks(["HIPAA_MINIMUM_NECESSARY"], unknown),
                   "HIPAA_MINIMUM_NECESSARY") == CheckStatus.ADVISORY.value


def test_authorization_required_for_non_tpo():
    # Marketing is non-TPO and needs a signed authorization -> block if absent.
    no_auth = {"phi_disclosure": {"purpose": "marketing", "fields": ["name", "email"]}}
    assert _status(run_checks(["HIPAA_AUTHORIZATION"], no_auth),
                   "HIPAA_AUTHORIZATION") == CheckStatus.BLOCK.value
    # Expired authorization is still invalid.
    expired = {"phi_disclosure": {"purpose": "marketing"},
               "authorization": {"signed": True, "expired": True}}
    assert _status(run_checks(["HIPAA_AUTHORIZATION"], expired),
                   "HIPAA_AUTHORIZATION") == CheckStatus.BLOCK.value
    # Valid signed authorization -> pass.
    ok = {"phi_disclosure": {"purpose": "marketing"},
          "authorization": {"signed": True}}
    assert _status(run_checks(["HIPAA_AUTHORIZATION"], ok),
                   "HIPAA_AUTHORIZATION") == CheckStatus.PASS.value
    # Treatment/payment/operations need no authorization -> N/A.
    tpo = {"phi_disclosure": {"purpose": "payment"}}
    assert _status(run_checks(["HIPAA_AUTHORIZATION"], tpo),
                   "HIPAA_AUTHORIZATION") == CheckStatus.NOT_APPLICABLE.value


def test_authorization_512_permitted_purposes_not_blocked():
    # 45 CFR 164.512 disclosures are permitted WITHOUT authorization -> N/A,
    # not a false BLOCK, even with no authorization on file.
    for purpose in ("public_health", "required_by_law", "health_oversight",
                    "law_enforcement"):
        ctx = {"phi_disclosure": {"purpose": purpose, "fields": ["name", "diagnosis_codes"]}}
        assert _status(run_checks(["HIPAA_AUTHORIZATION"], ctx),
                       "HIPAA_AUTHORIZATION") == CheckStatus.NOT_APPLICABLE.value
    # A genuinely authorization-required purpose still blocks without one.
    sale = {"phi_disclosure": {"purpose": "sale", "fields": ["name"]}}
    assert _status(run_checks(["HIPAA_AUTHORIZATION"], sale),
                   "HIPAA_AUTHORIZATION") == CheckStatus.BLOCK.value


def test_deidentification_safe_harbor():
    # "De-identified" claim that still carries identifiers -> block.
    leaky = {"deidentified_claim": True,
             "deidentified_payload": ["patient_name", "zip_code", "diagnosis_codes"]}
    assert _status(run_checks(["HIPAA_DEIDENTIFICATION"], leaky),
                   "HIPAA_DEIDENTIFICATION") == CheckStatus.BLOCK.value
    # Truly de-identified payload -> pass.
    clean = {"deidentified_claim": True,
             "deidentified_payload": ["diagnosis_codes", "procedure_codes", "gender"]}
    assert _status(run_checks(["HIPAA_DEIDENTIFICATION"], clean),
                   "HIPAA_DEIDENTIFICATION") == CheckStatus.PASS.value
    # No de-identification claimed -> checker does not fire.
    assert _status(run_checks(["HIPAA_DEIDENTIFICATION"], {}),
                   "HIPAA_DEIDENTIFICATION") == CheckStatus.NOT_APPLICABLE.value
    # Claimed but no payload -> ADVISORY.
    assert _status(run_checks(["HIPAA_DEIDENTIFICATION"], {"deidentified_claim": True}),
                   "HIPAA_DEIDENTIFICATION") == CheckStatus.ADVISORY.value


def test_deidentification_no_substring_false_positives():
    # 'toxicity_grade' (has 'city'), 'medication_name'/'procedure_name' (have
    # 'name') are NOT HIPAA identifiers -> the de-identified claim must PASS.
    clean = {"deidentified_claim": True,
             "deidentified_payload": ["toxicity_grade", "medication_name",
                                      "procedure_name", "diagnosis_codes"]}
    assert _status(run_checks(["HIPAA_DEIDENTIFICATION"], clean),
                   "HIPAA_DEIDENTIFICATION") == CheckStatus.PASS.value
    # Real word-boundary identifiers still caught: 'city', 'patient_name'.
    leaky = {"deidentified_claim": True,
             "deidentified_payload": ["city", "patient_name"]}
    assert _status(run_checks(["HIPAA_DEIDENTIFICATION"], leaky),
                   "HIPAA_DEIDENTIFICATION") == CheckStatus.BLOCK.value


def test_part2_requires_consent():
    # SUD records (ICD-10 F10-F19) disclosed with no consent -> block.
    sud = {"phi_disclosure": {"purpose": "treatment", "diagnosis_codes": ["F10.20"]}}
    assert _status(run_checks(["PART2"], sud), "PART2") == CheckStatus.BLOCK.value
    # Flagged Part 2 records with signed consent -> pass.
    ok = {"part2_records": True, "part2_consent": {"signed": True}}
    assert _status(run_checks(["PART2"], ok), "PART2") == CheckStatus.PASS.value
    # Revoked consent -> block.
    revoked = {"part2_records": True, "part2_consent": {"signed": True, "revoked": True}}
    assert _status(run_checks(["PART2"], revoked), "PART2") == CheckStatus.BLOCK.value
    # Expired consent cannot support disclosure under 42 CFR 2.31 -> block.
    expired = {"part2_records": True, "part2_consent": {"signed": True, "expired": True}}
    assert _status(run_checks(["PART2"], expired), "PART2") == CheckStatus.BLOCK.value
    # Non-SUD records -> not applicable.
    non_sud = {"phi_disclosure": {"purpose": "treatment", "diagnosis_codes": ["E11.9"]}}
    assert _status(run_checks(["PART2"], non_sud), "PART2") == CheckStatus.NOT_APPLICABLE.value
