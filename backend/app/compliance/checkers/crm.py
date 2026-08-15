"""CRM / Sales department data-privacy checkers: GDPR lawful basis, CCPA
opt-out of sale, TCPA do-not-contact, and DSAR statutory deadlines.

Deterministic, no LLM / no DB / no network. Each reads the structured facts it
needs from the gate ``context`` and returns a citation-backed verdict. An
absent required input yields ADVISORY (never a silent PASS); an action that
does not touch the regime yields NOT_APPLICABLE.
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta

from app.compliance.base import CheckResult, CheckStatus, Finding
from app.compliance.registry import register

_DEPT = "sales"

# GDPR Art 6(1) lawful bases for processing personal data.
_LAWFUL_BASES = {
    "consent", "contract", "legal_obligation", "vital_interests",
    "public_task", "legitimate_interests",
}

# Actions that constitute a "sale" or "share" of personal data under CCPA/CPRA.
_SALE_ACTIONS = {"sell", "sell_data", "share", "share_data", "sale"}

# Actions that constitute a call/SMS under the TCPA.
_TELECOM_ACTIONS = {"call", "sms", "text", "robocall", "autodial", "prerecorded"}

# TCPA 47 USC 227(b): autodialed / prerecorded / SMS to a wireless number needs
# PRIOR EXPRESS CONSENT; absence of consent is itself the violation. Manual,
# non-autodialed live calls fall under the DNC regime, not 227(b) consent.
_CONSENT_REQUIRED_ACTIONS = {"sms", "text", "robocall", "autodial", "prerecorded"}

# DSAR statutory response windows. GDPR Art 12(3) is ONE CALENDAR MONTH (handled
# as a date, below); CCPA is a flat day-count.
_DSAR_REGIMES = {"GDPR", "CCPA"}
_CCPA_DEADLINE_DAYS = 45
_FULFILLED = {"fulfilled", "completed", "closed", "done", "resolved"}


def _to_date(v):
    """Parse an ISO date string or pass through a date; None on empty."""
    if isinstance(v, date):
        return v
    return date.fromisoformat(v) if v else None


def _digits(n) -> str:
    """Normalise a phone number to its comparable digits so DNC matching is
    robust to spaces, dashes, parens, and a leading country code. Keeps the
    last 10 digits (the national significant number) so +1-555-123-4567 and
    (555) 123-4567 match.
    # ponytail: last-10-digits heuristic fits NANP; carry full E.164 if you
    # onboard numbers whose national part is not 10 digits."""
    d = "".join(ch for ch in str(n or "") if ch.isdigit())
    return d[-10:] if len(d) >= 10 else d


def _add_calendar_month(d: date) -> date:
    """One calendar month per GDPR Art 12(3) / Reg (EU) 1182/71: the same
    numbered day of the next month, clamped to that month's last day when it is
    shorter (e.g. 31 Jan -> 28/29 Feb)."""
    year = d.year + (d.month // 12)
    month = d.month % 12 + 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, last))


@register("GDPR", department=_DEPT,
          title="GDPR lawful basis for processing",
          citation="GDPR Art 6 (Regulation (EU) 2016/679)")
def check_gdpr_lawful_basis(context: dict) -> CheckResult:
    """Any processing of personal data needs one of the six Art 6 lawful bases;
    consent-based processing additionally needs affirmative consent. Needs
    ``context['processing']`` = {lawful_basis, consent?}."""
    proc = context.get("processing")
    if proc is None:
        return CheckResult("GDPR", CheckStatus.NOT_APPLICABLE, [],
                           method="deterministic")

    basis = str(proc.get("lawful_basis") or "").strip().lower()
    if not basis:
        return CheckResult("GDPR", CheckStatus.ADVISORY,
                           [Finding("no_lawful_basis",
                                    "No Art 6 lawful basis recorded for this "
                                    "processing action; cannot verify.", "MEDI")],
                           method="deterministic")
    if basis not in _LAWFUL_BASES:
        return CheckResult("GDPR", CheckStatus.BLOCK,
                           [Finding("invalid_lawful_basis",
                                    f"'{basis}' is not a valid GDPR Art 6 lawful "
                                    "basis; processing has no lawful ground.", "HIGH")],
                           method="deterministic")
    if basis == "consent" and proc.get("consent") is not True:
        return CheckResult("GDPR", CheckStatus.BLOCK,
                           [Finding("no_consent",
                                    "Consent-based processing requires affirmative "
                                    "consent (consent=true); none is recorded.", "HIGH")],
                           method="deterministic")
    return CheckResult("GDPR", CheckStatus.PASS, [], method="deterministic")


@register("CCPA", department=_DEPT,
          title="CCPA/CPRA opt-out of sale or sharing",
          citation="CCPA Cal. Civ. Code 1798.120")
def check_ccpa_opt_out(context: dict) -> CheckResult:
    """A consumer who has opted out of the sale/sharing of their personal data
    cannot have it sold or shared. Applies only to sale/share actions. Needs
    ``context['action']`` (or ``is_sale``) and ``context['data_subject']`` =
    {opted_out_of_sale?}."""
    action = str(context.get("action") or "").strip().lower()
    if action not in _SALE_ACTIONS and not context.get("is_sale"):
        return CheckResult("CCPA", CheckStatus.NOT_APPLICABLE, [],
                           method="deterministic")

    subject = context.get("data_subject") or {}
    opted_out = subject.get("opted_out_of_sale")
    if opted_out is None:
        return CheckResult("CCPA", CheckStatus.ADVISORY,
                           [Finding("no_optout_status",
                                    "Consumer sale opt-out status is unknown; "
                                    "cannot verify the sale is permitted.", "MEDI")],
                           method="deterministic")
    if opted_out:
        return CheckResult("CCPA", CheckStatus.BLOCK,
                           [Finding("sale_after_optout",
                                    "This consumer opted out of the sale/sharing "
                                    "of their personal data; the sale is prohibited.", "HIGH")],
                           method="deterministic")
    return CheckResult("CCPA", CheckStatus.PASS, [], method="deterministic")


@register("TCPA", department=_DEPT,
          title="TCPA do-not-contact / opt-out for calls and SMS",
          citation="Telephone Consumer Protection Act 47 U.S.C. 227")
def check_tcpa_contact(context: dict) -> CheckResult:
    """No call or SMS may go to a number on the Do-Not-Contact list or to a
    consumer who has opted out of contact. Applies only to call/SMS actions.
    Needs ``context['action']``, ``context['phone']``,
    ``context['do_not_contact']`` (list), and optional
    ``context['data_subject']`` = {opted_out_of_contact?}."""
    action = str(context.get("action") or "").strip().lower()
    channel = str(context.get("channel") or "").strip().lower()
    if action not in _TELECOM_ACTIONS and channel not in _TELECOM_ACTIONS:
        return CheckResult("TCPA", CheckStatus.NOT_APPLICABLE, [],
                           method="deterministic")

    phone = context.get("phone") or context.get("target_number")
    subject = context.get("data_subject") or {}
    if not phone:
        return CheckResult("TCPA", CheckStatus.ADVISORY,
                           [Finding("no_target_number",
                                    "No target number supplied; cannot verify it "
                                    "is off the do-not-contact list.", "MEDI")],
                           method="deterministic")

    dnc = {_digits(n) for n in (context.get("do_not_contact") or [])}
    if _digits(phone) in dnc:
        return CheckResult("TCPA", CheckStatus.BLOCK,
                           [Finding("on_do_not_contact",
                                    f"Number {phone} is on the do-not-contact list; "
                                    "calling or texting it is prohibited.", "HIGH")],
                           method="deterministic")
    if subject.get("opted_out_of_contact"):
        return CheckResult("TCPA", CheckStatus.BLOCK,
                           [Finding("contact_after_optout",
                                    f"Consumer at {phone} opted out of contact; "
                                    "calling or texting is prohibited.", "HIGH")],
                           method="deterministic")

    # 47 USC 227(b): autodial / prerecorded / SMS needs PRIOR EXPRESS CONSENT.
    # Absence of consent is the violation, so fail closed.
    consent = subject.get("consent")
    if consent is None:
        consent = context.get("consent")
    if (action in _CONSENT_REQUIRED_ACTIONS or channel in _CONSENT_REQUIRED_ACTIONS) \
            and consent is not True:
        return CheckResult("TCPA", CheckStatus.BLOCK,
                           [Finding("no_prior_consent",
                                    f"Autodialed/prerecorded/SMS contact to {phone} "
                                    "requires prior express consent (47 USC 227(b)); "
                                    "none is recorded.", "HIGH")],
                           method="deterministic")

    # A clean number is not enough: with neither a do-not-contact list nor any
    # opt-out/consent status supplied, nothing was actually verified.
    dnc_supplied = context.get("do_not_contact") is not None
    optout_supplied = "opted_out_of_contact" in subject or consent is not None
    if not dnc_supplied and not optout_supplied:
        return CheckResult("TCPA", CheckStatus.ADVISORY,
                           [Finding("no_dnc_list",
                                    "No do-not-contact list and no opt-out/consent "
                                    "status supplied; cannot verify contact is "
                                    "permitted.", "MEDI")],
                           method="deterministic")
    return CheckResult("TCPA", CheckStatus.PASS, [], method="deterministic")


@register("DSAR", department=_DEPT,
          title="Data-subject request response deadline",
          citation="GDPR Art 12(3); CCPA Cal. Civ. Code 1798.130")
def check_dsar_deadline(context: dict) -> CheckResult:
    """A data-subject access or deletion request must be fulfilled within the
    statutory window (GDPR one calendar month, CCPA 45 days). Needs
    ``context['dsar']`` = {regime, request_date, fulfilled_date?, status?,
    as_of?, extension_days?, extension_noticed?}. Because it is a
    pure function, the elapsed time is measured against ``fulfilled_date`` if
    fulfilled, else an explicit ``as_of`` evaluation date."""
    dsar = context.get("dsar")
    if not dsar:
        return CheckResult("DSAR", CheckStatus.NOT_APPLICABLE, [],
                           method="deterministic")

    regime = str(dsar.get("regime") or "").strip().upper()
    if regime not in _DSAR_REGIMES:
        return CheckResult("DSAR", CheckStatus.ADVISORY,
                           [Finding("unknown_regime",
                                    "DSAR regime is not GDPR or CCPA; the response "
                                    "deadline cannot be determined.", "MEDI")],
                           method="deterministic")

    try:
        requested = _to_date(dsar.get("request_date"))
        fulfilled = _to_date(dsar.get("fulfilled_date"))
        as_of = _to_date(dsar.get("as_of") or context.get("as_of"))
    except (ValueError, TypeError):
        return CheckResult("DSAR", CheckStatus.ADVISORY,
                           [Finding("bad_dates", "DSAR dates are unparseable.", "MEDI")],
                           method="deterministic")

    if requested is None:
        return CheckResult("DSAR", CheckStatus.ADVISORY,
                           [Finding("no_request_date",
                                    "No request date recorded; cannot measure the "
                                    "response window.", "MEDI")],
                           method="deterministic")

    status = str(dsar.get("status") or "").strip().lower()
    is_fulfilled = fulfilled is not None or status in _FULFILLED
    reference = fulfilled or as_of
    if reference is None:
        return CheckResult("DSAR", CheckStatus.ADVISORY,
                           [Finding("no_reference_date",
                                    "Request is still open with no evaluation date; "
                                    "cannot measure whether the deadline has passed.", "MEDI")],
                           method="deterministic")

    elapsed = (reference - requested).days
    if elapsed < 0:
        return CheckResult("DSAR", CheckStatus.ADVISORY,
                           [Finding("bad_dates",
                                    "The fulfilment/evaluation date precedes the "
                                    "request date; cannot measure the window.", "MEDI")],
                           method="deterministic")

    # GDPR Art 12(3) is one CALENDAR month; CCPA is a flat 45-day count.
    if regime == "GDPR":
        deadline_date = _add_calendar_month(requested)
        limit_desc = "one calendar month"
    else:
        deadline_date = requested + timedelta(days=_CCPA_DEADLINE_DAYS)
        limit_desc = f"{_CCPA_DEADLINE_DAYS} days"

    # Art 12(3)/1798.130(b): a further extension when timely notice was given.
    ext = dsar.get("extension_days")
    if ext and dsar.get("extension_noticed"):
        deadline_date = deadline_date + timedelta(days=int(ext))

    if reference > deadline_date:
        verb = "was fulfilled" if is_fulfilled else "has been open"
        return CheckResult("DSAR", CheckStatus.BLOCK,
                           [Finding("past_deadline",
                                    f"{regime} data-subject request {verb} {elapsed} "
                                    f"days after receipt; the statutory deadline is "
                                    f"{limit_desc}.", "HIGH")],
                           method="deterministic")
    return CheckResult("DSAR", CheckStatus.PASS, [], method="deterministic")
