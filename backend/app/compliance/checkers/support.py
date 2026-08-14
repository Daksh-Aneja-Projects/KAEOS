"""Customer Support statutory checkers: PII redaction, call-recording consent,
SLA breach. Deterministic regex + Luhn only - no LLM, no DB, no network.

Each reads structured facts from the gate ``context`` and returns a
citation-backed verdict. Finding messages never echo the raw PII/secret they
detect (that would leak it into the audit log); they report the type and count.
"""
from __future__ import annotations

import re
from datetime import datetime

from app.compliance.base import CheckResult, CheckStatus, Finding
from app.compliance.registry import register

_DEPT = "support"

# --- PII_REDACTION ----------------------------------------------------------

# Candidate card: any maximal run of >=13 digits, optionally split by single
# spaces/dashes. We slide inside each run so a PAN glued to adjacent digits
# ('994111...') cannot evade a whole-run-only Luhn test.
_CARD_CANDIDATE = re.compile(r"\d(?:[ \-]?\d){12,}")
# A 15-digit IMEI is Luhn-valid too, so require a card IIN prefix (3-6) or a
# nearby card keyword before treating a Luhn-valid run as a PAN.
_CARD_KEYWORDS = re.compile(r"(?i)card|visa|master|amex|discover|credit|debit|\bpan\b|cvv|cvc|expir")
# SSN in canonical separated form.
_SSN = re.compile(r"\b(?!000|666|9\d\d)\d{3}[ \-](?!00)\d{2}[ \-](?!0000)\d{4}\b")
# Bare 9-digit SSN (no separators): validate area/group/serial so we do not
# flag every 9-digit order/phone number.
# ponytail: naive area/group/serial gate, still false-positive-prone on 9-digit
# ids; tighten with an SSN keyword-proximity check if a caller reports noise.
_SSN_BARE = re.compile(r"\b(?!000|666|9\d\d)\d{3}(?!00)\d{2}(?!0000)\d{4}\b")
# Well-known API-key / token shapes.
_API_KEY_RES = [
    re.compile(r"\bA(?:KIA|SIA)[0-9A-Z]{16}\b"),                     # AWS key id
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),                          # OpenAI-style
    re.compile(r"\b(?:sk|pk|rk)_(?:live|test)_[A-Za-z0-9]{16,}\b"),  # Stripe
    re.compile(r"\bgh[posru]_[A-Za-z0-9]{20,}\b"),                   # GitHub PAT
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),                 # Slack
    re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),                       # Google API
    re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b"),  # JWT
    re.compile(r"(?i)(?:api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{16,}"),
]

_TEXT_KEYS = ("outbound_text", "message", "body", "reply", "text",
              "ticket_text", "content", "note")
_LIST_KEYS = ("messages", "comments")


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = ord(ch) - 48
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def _has_card(digits: str, keyword_near: bool) -> bool:
    """Slide a 13-19-length window over one maximal digit run and Luhn-test each,
    so a PAN embedded in a longer run is caught. A window only counts as a card
    if it starts with a card IIN digit (3-6) or a card keyword sat nearby, so a
    Luhn-valid IMEI/other id is not mis-flagged as a PAN."""
    n = len(digits)
    for length in range(13, 20):
        for i in range(0, n - length + 1):
            sub = digits[i:i + length]
            if (sub[0] in "3456" or keyword_near) and _luhn(sub):
                return True
    return False


def _collect_text(context: dict) -> str:
    parts = []
    for k in _TEXT_KEYS:
        v = context.get(k)
        if isinstance(v, str):
            parts.append(v)
    for k in _LIST_KEYS:
        for item in context.get(k) or []:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                for kk in ("body", "text", "message", "content"):
                    if isinstance(item.get(kk), str):
                        parts.append(item[kk])
    return "\n".join(parts)


@register("PII_REDACTION", department=_DEPT,
          title="Outbound PII redaction (card / SSN / API key)",
          citation="PCI-DSS v4.0 Req. 3.3 (PAN masking); FTC Safeguards Rule 16 CFR 314")
def check_pii_redaction(context: dict) -> CheckResult:
    """An outbound support message must not carry unredacted sensitive
    identifiers. Detects credit-card numbers (Luhn-valid), US SSNs, and
    API-key-like secrets. Needs one of the text keys (``outbound_text``,
    ``message``, ``body`` ...) or ``messages``/``comments`` lists."""
    text = _collect_text(context)
    if not text.strip():
        return CheckResult("PII_REDACTION", CheckStatus.NOT_APPLICABLE, [],
                           method="deterministic")

    cards = 0
    for m in _CARD_CANDIDATE.finditer(text):
        digits = m.group().replace(" ", "").replace("-", "")
        window = text[max(0, m.start() - 24): m.end() + 24]
        keyword_near = bool(_CARD_KEYWORDS.search(window))
        if _has_card(digits, keyword_near):
            cards += 1
    ssns = len(_SSN.findall(text)) + len(_SSN_BARE.findall(text))
    keys = sum(len(rx.findall(text)) for rx in _API_KEY_RES)

    findings = []
    if cards:
        findings.append(Finding("unredacted_card",
                                f"Outbound text carries {cards} unredacted "
                                "credit-card number(s) (Luhn-valid); PANs must be "
                                "masked before leaving the platform.", "CRIT"))
    if ssns:
        findings.append(Finding("unredacted_ssn",
                                f"Outbound text carries {ssns} unredacted US Social "
                                "Security number(s).", "CRIT"))
    if keys:
        findings.append(Finding("unredacted_secret",
                                f"Outbound text carries {keys} API-key-like "
                                "secret token(s) in the clear.", "HIGH"))
    status = CheckStatus.BLOCK if findings else CheckStatus.PASS
    return CheckResult("PII_REDACTION", status, findings, method="regex_luhn",
                       detail={"cards": cards, "ssns": ssns, "secrets": keys})


# --- CALL_RECORDING_CONSENT -------------------------------------------------

# All-party ("two-party") consent states, conservative widely-cited set. A
# caller can force the regime with context['call_recording']['two_party']=True.
_TWO_PARTY_STATES = {
    "CA", "CT", "DE", "FL", "IL", "MD", "MA", "MT", "NV", "NH", "PA", "WA",
    "CALIFORNIA", "CONNECTICUT", "DELAWARE", "FLORIDA", "ILLINOIS",
    "MARYLAND", "MASSACHUSETTS", "MONTANA", "NEVADA", "NEW HAMPSHIRE",
    "PENNSYLVANIA", "WASHINGTON",
}


@register("CALL_RECORDING_CONSENT", department=_DEPT,
          title="Two-party-consent call recording",
          citation="Cal. Penal Code 632 (CIPA); 18 U.S.C. 2511 (Federal Wiretap Act)")
def check_call_recording_consent(context: dict) -> CheckResult:
    """In an all-party (two-party) consent jurisdiction, recording a call
    requires captured consent from all parties. Needs
    ``context['call_recording']`` = {recording: bool, state|jurisdiction: str,
    two_party?: bool, consent_captured: bool}."""
    cr = context.get("call_recording")
    if not cr or not cr.get("recording"):
        return CheckResult("CALL_RECORDING_CONSENT", CheckStatus.NOT_APPLICABLE, [],
                           method="deterministic")

    # The explicit two_party flag may only TIGHTEN (add an all-party rule), never
    # LOOSEN one a jurisdiction already imposes: two_party=False cannot downgrade
    # an all-party state to one-party.
    explicit = cr.get("two_party")
    state = str(cr.get("state") or cr.get("jurisdiction") or "").strip().upper()
    juris = state in _TWO_PARTY_STATES if state else None  # True / False / None

    if juris is True or explicit is True:
        all_party = True
    elif explicit is False or juris is False:
        all_party = False
    else:
        all_party = None  # unknown jurisdiction and no explicit flag

    if all_party is None:
        return CheckResult("CALL_RECORDING_CONSENT", CheckStatus.ADVISORY,
                           [Finding("unknown_jurisdiction",
                                    "Call is being recorded but no jurisdiction "
                                    "was supplied; consent requirement cannot be "
                                    "verified.", "MEDI")],
                           method="deterministic")

    if not all_party:
        # One-party-consent context: the recording party's own consent suffices.
        return CheckResult("CALL_RECORDING_CONSENT", CheckStatus.PASS, [],
                           method="deterministic")

    if cr.get("consent_captured"):
        return CheckResult("CALL_RECORDING_CONSENT", CheckStatus.PASS, [],
                           method="deterministic")
    return CheckResult("CALL_RECORDING_CONSENT", CheckStatus.BLOCK,
                       [Finding("no_recording_consent",
                                "Recording a call in an all-party-consent "
                                "jurisdiction without captured consent from all "
                                "parties is a wiretap violation.", "CRIT")],
                       method="deterministic")


# --- SLA_BREACH -------------------------------------------------------------

_SLA_HOURS = {
    "urgent": 4, "critical": 4, "p1": 4,
    "high": 8, "p2": 8,
    "normal": 24, "medium": 24, "standard": 24, "p3": 24,
    "low": 72, "p4": 72,
}


def _dt(v):
    if isinstance(v, datetime):
        return v
    return datetime.fromisoformat(str(v)) if v else None


@register("SLA_BREACH", department=_DEPT,
          title="Ticket SLA breach (advisory)",
          citation="Internal support SLA policy")
def check_sla_breach(context: dict) -> CheckResult:
    """Advisory when a ticket has sat past its priority SLA. Needs
    ``context['ticket']`` = {priority, age_hours} OR {priority, opened_at,
    now|as_of[, resolved_at]}. Optional ``sla_hours`` overrides the table."""
    ticket = context.get("ticket")
    if not ticket:
        return CheckResult("SLA_BREACH", CheckStatus.NOT_APPLICABLE, [],
                           method="deterministic")

    priority = str(ticket.get("priority") or "").strip().lower()
    sla = ticket.get("sla_hours") or _SLA_HOURS.get(priority)
    if sla is None:
        return CheckResult("SLA_BREACH", CheckStatus.ADVISORY,
                           [Finding("unknown_priority",
                                    f"Ticket priority '{ticket.get('priority')}' is not "
                                    "in the SLA table; breach cannot be measured.", "LOW")],
                           method="deterministic")

    age_hours = ticket.get("age_hours")
    if age_hours is None:
        try:
            opened = _dt(ticket.get("opened_at") or ticket.get("created_at"))
            ref = _dt(ticket.get("resolved_at") or ticket.get("now") or ticket.get("as_of"))
        except (ValueError, TypeError):
            opened = ref = None
        if opened is None or ref is None:
            return CheckResult("SLA_BREACH", CheckStatus.ADVISORY,
                               [Finding("no_timing",
                                        "Ticket timing (age_hours or opened_at + now) "
                                        "is missing; SLA breach cannot be measured.",
                                        "LOW")],
                               method="deterministic")
        age_hours = (ref - opened).total_seconds() / 3600.0

    try:
        age_hours = float(age_hours)
        sla = float(sla)
    except (ValueError, TypeError):
        return CheckResult("SLA_BREACH", CheckStatus.ADVISORY,
                           [Finding("bad_timing", "Ticket timing values unparseable.", "LOW")],
                           method="deterministic")

    if age_hours > sla:
        return CheckResult("SLA_BREACH", CheckStatus.ADVISORY,
                           [Finding("sla_breached",
                                    f"Ticket has been open {age_hours:.1f}h, past its "
                                    f"{sla:.0f}h {priority or 'priority'} SLA.", "MEDI")],
                           method="deterministic",
                           detail={"age_hours": age_hours, "sla_hours": sla})
    return CheckResult("SLA_BREACH", CheckStatus.PASS, [], method="deterministic",
                       detail={"age_hours": age_hours, "sla_hours": sla})
