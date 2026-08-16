"""Healthcare department statutory checkers: HIPAA Privacy Rule + 42 CFR Part 2.

Deterministic, no LLM / DB / network. Each reads the structured PHI-disclosure
facts from the gate ``context`` and returns a citation-backed verdict. This is
the healthcare vertical's load-bearing privacy control.

Expected context shape (all optional; a checker returns NOT_APPLICABLE when the
action does not touch its regime, ADVISORY when it cannot verify)::

    context["phi_disclosure"] = {
        "purpose": "payment" | "treatment" | "marketing" | ...,
        "fields": ["name", "diagnosis_codes", "ssn", ...],   # or a {field: value} dict
        "diagnosis_codes": ["F10.20", ...],                  # optional
    }
    context["authorization"]   = {"signed": bool, "expired": bool, "revoked": bool}
    context["deidentified_claim"] = bool
    context["deidentified_payload"] = {field: value} | [field, ...]
    context["part2_records"]   = bool
    context["part2_consent"]   = {"signed": bool, "revoked": bool}
"""
from __future__ import annotations

from app.compliance.base import CheckResult, CheckStatus, Finding
from app.compliance.registry import register

_DEPT = "healthcare"

# Treatment, Payment, health-care Operations - the disclosures that do NOT need
# a patient authorization under HIPAA (45 CFR 164.506).
_TPO = {"treatment", "payment", "billing", "healthcare_operations",
        "health_care_operations", "operations", "tpo"}

# 45 CFR 164.512 permits these disclosures WITHOUT patient authorization.
_512_PERMITTED = {"public_health", "public_health_activities",
                  "required_by_law", "health_oversight",
                  "health_oversight_activities", "judicial", "judicial_proceeding",
                  "law_enforcement", "coroner", "medical_examiner",
                  "organ_donation", "research_waiver", "serious_threat",
                  "workers_compensation", "workers_comp"}

# Minimum-necessary does not apply to treatment disclosures, disclosures to the
# individual, or those made under a valid authorization (45 CFR 164.502(b)(2)).
_MIN_NEC_EXEMPT = {"treatment", "to_individual", "individual",
                   "required_by_law", "authorization"}

# Purpose -> the field set reasonably needed for it. A disclosure that ships
# fields beyond this set violates the minimum-necessary standard, 164.502(b).
_PURPOSE_ALLOWED = {
    "payment": {"name", "dob", "member_id", "insurance_id", "subscriber_id",
                "dates_of_service", "procedure_codes", "cpt_codes",
                "diagnosis_codes", "billing_amount", "provider", "npi"},
    "billing": {"name", "dob", "member_id", "insurance_id", "subscriber_id",
                "dates_of_service", "procedure_codes", "cpt_codes",
                "diagnosis_codes", "billing_amount", "provider", "npi"},
    "appointment_reminder": {"name", "phone", "email", "appointment_date",
                             "provider", "location"},
    "quality_measurement": {"member_id", "diagnosis_codes", "procedure_codes",
                            "dates_of_service"},
    "healthcare_operations": {"member_id", "diagnosis_codes", "procedure_codes",
                              "dates_of_service", "provider", "npi"},
}

# The 18 HIPAA Safe Harbor identifiers (45 CFR 164.514(b)(2)), matched by
# field-name token. ponytail: field-name scan only; value-level checks (an age
# over 89, a ZIP with < 20k population) would need the actual values - add a
# value inspector here if payloads start carrying them.
_HIPAA_IDENTIFIER_TOKENS = {
    "names": ("name",),
    "geographic_subdivision": ("address", "street", "city", "county", "zip",
                               "postal", "precinct"),
    "dates": ("birth", "dob", "admission", "admit_date", "discharge",
              "death_date", "date_of_", "service_date", "dates_of_service",
              # Safe Harbor removes ALL date elements finer than a year, so a
              # general date/dates segment is an identifier - not just the
              # enumerated ones above (service dates were slipping through).
              "date", "dates"),
    "phone": ("phone", "telephone"),
    "fax": ("fax",),
    "email": ("email",),
    "ssn": ("ssn", "social_security"),
    "medical_record_number": ("mrn", "medical_record", "record_number"),
    "health_plan_number": ("beneficiary", "health_plan", "member_id",
                           "subscriber"),
    "account_number": ("account_number", "acct"),
    "license_number": ("license", "certificate_number"),
    "vehicle_id": ("vin", "license_plate", "vehicle_id"),
    "device_id": ("device_id", "device_serial", "serial_number"),
    "url": ("url", "website"),
    "ip_address": ("ip_address", "ipaddr"),
    "biometric": ("fingerprint", "voiceprint", "biometric", "retina",
                  "iris_scan"),
    "full_face_photo": ("photo", "face_image", "facial_image"),
    "other_unique_id": ("patient_id", "unique_id"),
}

# ICD-10 substance-use-disorder code families F10-F19 (42 CFR Part 2 records).
_SUD_ICD10 = tuple(f"f1{n}" for n in range(0, 10))


def _norm(v: str) -> str:
    return str(v).strip().lower().replace(" ", "_").replace("-", "_")


# "name" alone is a person-name identifier; qualified by a clinical object it is
# not (medication_name, procedure_name). Small denylist, extend as fields appear.
_NON_PERSON_NAME_QUALIFIERS = {"medication", "drug", "procedure", "product",
                               "device", "test", "lab", "facility", "file",
                               "field", "table", "event", "brand", "generic"}


def _field_has_token(field: str, token: str) -> bool:
    """Word-boundary match: the token's ``_``-segments appear as a contiguous run
    of the field's segments. Avoids substring false hits ('city' in 'toxicity',
    'name' in 'medication_name')."""
    fsegs = field.split("_")
    tsegs = token.strip("_").split("_")
    n = len(tsegs)
    for i in range(len(fsegs) - n + 1):
        if fsegs[i:i + n] != tsegs:
            continue
        if tsegs == ["name"] and i > 0 and fsegs[i - 1] in _NON_PERSON_NAME_QUALIFIERS:
            continue
        return True
    return False


def _disclosure(context: dict) -> dict:
    return context.get("phi_disclosure") or context.get("disclosure") or {}


def _field_set(raw) -> set:
    if isinstance(raw, dict):
        raw = list(raw.keys())
    if isinstance(raw, str):
        raw = [raw]
    return {_norm(f) for f in (raw or [])}


@register("HIPAA_MINIMUM_NECESSARY", department=_DEPT,
          title="HIPAA minimum-necessary PHI disclosure",
          citation="45 CFR 164.502(b); 45 CFR 164.514(d)")
def check_minimum_necessary(context: dict) -> CheckResult:
    """A PHI disclosure must be limited to the fields minimally necessary for its
    stated purpose. Blocks when disclosed fields exceed the purpose's allowed
    set. Treatment / to-individual / authorization disclosures are exempt."""
    d = _disclosure(context)
    if not d:
        return CheckResult("HIPAA_MINIMUM_NECESSARY", CheckStatus.NOT_APPLICABLE, [],
                           method="deterministic")
    purpose = _norm(d.get("purpose") or "")
    if purpose in _MIN_NEC_EXEMPT:
        return CheckResult("HIPAA_MINIMUM_NECESSARY", CheckStatus.NOT_APPLICABLE, [],
                           method="deterministic",
                           detail={"purpose": purpose, "exempt": True})
    fields = _field_set(d.get("fields"))
    if not fields:
        return CheckResult("HIPAA_MINIMUM_NECESSARY", CheckStatus.ADVISORY,
                           [Finding("no_fields",
                                    "PHI disclosure lists no fields; the minimum-necessary "
                                    "scope cannot be verified.", "MEDI")],
                           method="deterministic", detail={"purpose": purpose})
    allowed = _PURPOSE_ALLOWED.get(purpose)
    if allowed is None:
        return CheckResult("HIPAA_MINIMUM_NECESSARY", CheckStatus.ADVISORY,
                           [Finding("unknown_purpose",
                                    f"No minimum-necessary field policy is defined for "
                                    f"purpose '{purpose}'; disclosure scope cannot be "
                                    "verified.", "MEDI")],
                           method="deterministic", detail={"purpose": purpose})
    extra = sorted(fields - allowed)
    if extra:
        return CheckResult("HIPAA_MINIMUM_NECESSARY", CheckStatus.BLOCK,
                           [Finding("excess_fields",
                                    f"Disclosure for '{purpose}' includes fields beyond the "
                                    f"minimum necessary: {', '.join(extra)}.", "HIGH")],
                           method="deterministic",
                           detail={"purpose": purpose, "excess": extra})
    return CheckResult("HIPAA_MINIMUM_NECESSARY", CheckStatus.PASS, [],
                       method="deterministic", detail={"purpose": purpose})


@register("HIPAA_AUTHORIZATION", department=_DEPT,
          title="HIPAA authorization for non-TPO disclosure",
          citation="45 CFR 164.508")
def check_authorization(context: dict) -> CheckResult:
    """A disclosure for any purpose other than treatment, payment, or health-care
    operations requires a valid signed patient authorization on file. Blocks when
    the authorization is absent, unsigned, expired, or revoked."""
    d = _disclosure(context)
    if not d:
        return CheckResult("HIPAA_AUTHORIZATION", CheckStatus.NOT_APPLICABLE, [],
                           method="deterministic")
    purpose = _norm(d.get("purpose") or "")
    if purpose in _TPO:
        return CheckResult("HIPAA_AUTHORIZATION", CheckStatus.NOT_APPLICABLE, [],
                           method="deterministic",
                           detail={"purpose": purpose, "tpo": True})
    if purpose in _512_PERMITTED:
        return CheckResult("HIPAA_AUTHORIZATION", CheckStatus.NOT_APPLICABLE, [],
                           method="deterministic",
                           detail={"purpose": purpose, "permitted_512": True})
    auth = context.get("authorization") or d.get("authorization") or {}
    if not auth or not auth.get("signed"):
        return CheckResult("HIPAA_AUTHORIZATION", CheckStatus.BLOCK,
                           [Finding("no_authorization",
                                    f"Disclosure for non-TPO purpose '{purpose}' requires a "
                                    "signed patient authorization; none is on file.", "HIGH")],
                           method="deterministic", detail={"purpose": purpose})
    if auth.get("revoked") or auth.get("expired"):
        why = "revoked" if auth.get("revoked") else "expired"
        return CheckResult("HIPAA_AUTHORIZATION", CheckStatus.BLOCK,
                           [Finding("invalid_authorization",
                                    f"Patient authorization for '{purpose}' is {why} and "
                                    "cannot support this disclosure.", "HIGH")],
                           method="deterministic", detail={"purpose": purpose})
    return CheckResult("HIPAA_AUTHORIZATION", CheckStatus.PASS, [],
                       method="deterministic", detail={"purpose": purpose})


@register("HIPAA_DEIDENTIFICATION", department=_DEPT,
          title="HIPAA Safe Harbor de-identification",
          citation="45 CFR 164.514(b)")
def check_deidentification(context: dict) -> CheckResult:
    """Safe Harbor: a payload claimed to be de-identified must contain none of the
    18 HIPAA identifiers. Blocks the de-identified claim when any identifier field
    is present. Only fires when de-identification is actually claimed."""
    if not (context.get("deidentified_claim") or context.get("deidentified")):
        return CheckResult("HIPAA_DEIDENTIFICATION", CheckStatus.NOT_APPLICABLE, [],
                           method="deterministic")
    payload = context.get("deidentified_payload")
    fields = _field_set(payload) if payload is not None else _field_set(_disclosure(context).get("fields"))
    if not fields:
        return CheckResult("HIPAA_DEIDENTIFICATION", CheckStatus.ADVISORY,
                           [Finding("no_payload",
                                    "De-identification is claimed but no payload fields were "
                                    "supplied; the claim cannot be verified.", "MEDI")],
                           method="deterministic")
    found = sorted({
        cat for f in fields
        for cat, tokens in _HIPAA_IDENTIFIER_TOKENS.items()
        if any(_field_has_token(f, t) for t in tokens)
    })
    if found:
        return CheckResult("HIPAA_DEIDENTIFICATION", CheckStatus.BLOCK,
                           [Finding("identifiers_present",
                                    "Payload is claimed de-identified but still carries HIPAA "
                                    f"Safe Harbor identifiers: {', '.join(found)}.", "HIGH")],
                           method="deterministic", detail={"identifiers": found})
    return CheckResult("HIPAA_DEIDENTIFICATION", CheckStatus.PASS, [],
                       method="deterministic")


@register("PART2", department=_DEPT,
          title="42 CFR Part 2 substance-use-disorder consent",
          citation="42 CFR Part 2")
def check_part2(context: dict) -> CheckResult:
    """Substance-use-disorder records from a Part 2 program require specific
    patient consent before disclosure. Blocks when the records are SUD (flagged
    or carrying ICD-10 F10-F19 codes) and no signed consent is on file."""
    d = _disclosure(context)
    codes = [_norm(c) for c in (d.get("diagnosis_codes")
                                or context.get("diagnosis_codes") or [])]
    is_sud = bool(context.get("part2_records") or d.get("part2_records")
                  or any(c.startswith(_SUD_ICD10) for c in codes))
    if not is_sud:
        return CheckResult("PART2", CheckStatus.NOT_APPLICABLE, [],
                           method="deterministic")
    consent = (context.get("part2_consent") or context.get("sud_consent")
               or d.get("part2_consent") or {})
    if not consent or not consent.get("signed"):
        return CheckResult("PART2", CheckStatus.BLOCK,
                           [Finding("no_part2_consent",
                                    "Substance-use-disorder records require specific written "
                                    "patient consent before disclosure; none is on file.", "HIGH")],
                           method="deterministic")
    if consent.get("revoked") or consent.get("expired"):
        why = "revoked" if consent.get("revoked") else "expired"
        return CheckResult("PART2", CheckStatus.BLOCK,
                           [Finding("part2_consent_invalid",
                                    "The Part 2 consent for these substance-use-disorder "
                                    f"records is {why} and cannot support disclosure.", "HIGH")],
                           method="deterministic")
    return CheckResult("PART2", CheckStatus.PASS, [], method="deterministic")
