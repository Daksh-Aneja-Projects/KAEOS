"""Procurement department statutory / control checkers.

Deterministic, no LLM, no DB, no network. Each reads the structured facts it
needs from the gate ``context`` and returns a citation-backed verdict:

- THREE_WAY_MATCH   PO, goods receipt, and invoice quantities and unit prices
                    must agree within tolerance before a payment is released.
- SEGREGATION_OF_DUTIES  requester, approver, and receiver must be different
                    identities (four-eyes / COSO SoD).
- SPEND_AUTHORIZATION    the amount approved must sit within the approver's
                    delegated authority limit.
- OFAC_SANCTIONS    the vendor must not appear on a supplied denied-parties /
                    sanctions list.

Money is Decimal. Missing inputs return ADVISORY (never a silent PASS); a real
violation returns BLOCK; a regime the action does not touch returns
NOT_APPLICABLE.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from app.compliance.base import CheckResult, CheckStatus, Finding
from app.compliance.registry import register

_DEPT = "procurement"


def _dec(v, default: str = "0") -> Decimal:
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _dec_opt(v):
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _norm(s) -> str:
    return " ".join(str(s).strip().lower().split())


def _norm_punct(s) -> str:
    # Normalized AND stripped of punctuation, so 'L.L.C.' == 'LLC'.
    return "".join(ch for ch in _norm(s) if ch.isalnum() or ch.isspace())


@register("THREE_WAY_MATCH", department=_DEPT,
          title="Three-way match (PO, goods receipt, invoice)",
          citation="AICPA / COSO purchasing controls; SOX 404 three-way match (PO-receipt-invoice)")
def check_three_way_match(context: dict) -> CheckResult:
    """Quantities across PO, receipt, and invoice must agree within
    ``qty_tolerance`` and the invoice unit price must agree with the PO unit
    price within ``price_tolerance`` before a payment is released. Needs
    ``context['three_way_match']`` = a line dict (or list of them), each shaped
    {po:{qty,unit_price}, receipt:{qty}, invoice:{qty,unit_price}}. Optional
    top-level ``qty_tolerance`` / ``price_tolerance`` (absolute, default 0)."""
    twm = context.get("three_way_match") or context.get("match")
    if not twm:
        return CheckResult("THREE_WAY_MATCH", CheckStatus.NOT_APPLICABLE, [],
                           method="deterministic")
    lines = twm if isinstance(twm, list) else (twm.get("lines") or [twm])
    qty_tol = _dec(context.get("qty_tolerance"), "0")
    price_tol = _dec(context.get("price_tolerance"), "0")

    findings: list[Finding] = []
    advisory: list[Finding] = []
    for idx, ln in enumerate(lines):
        if not isinstance(ln, dict):
            advisory.append(Finding("bad_line", f"Line {idx + 1} is not a match record.", "MEDI"))
            continue
        tag = ln.get("line_id") or ln.get("sku") or f"line {idx + 1}"
        po = ln.get("po") or {}
        rc = ln.get("receipt") or {}
        inv = ln.get("invoice") or {}

        po_q, rc_q, inv_q = _dec_opt(po.get("qty")), _dec_opt(rc.get("qty")), _dec_opt(inv.get("qty"))
        qtys = [q for q in (po_q, rc_q, inv_q) if q is not None]
        if len(qtys) < 3:
            advisory.append(Finding("qty_unverifiable",
                                    f"{tag}: cannot verify quantity match; PO, receipt, and "
                                    "invoice quantities are not all present.", "MEDI"))
        else:
            # Payment-safety: the invoice may bill at most what was ordered AND
            # at most what was received. Under-billing (honest partial delivery)
            # and over-receipt are fine; only billing beyond either is a block.
            if inv_q - po_q > qty_tol:
                findings.append(Finding("qty_over_po",
                                        f"{tag}: invoice bills {inv_q} but only {po_q} was ordered "
                                        f"(over by {inv_q - po_q}, tolerance {qty_tol}). Do not "
                                        "release payment.", "HIGH"))
            elif inv_q - rc_q > qty_tol:
                findings.append(Finding("qty_over_receipt",
                                        f"{tag}: invoice bills {inv_q} but only {rc_q} was received "
                                        f"(over by {inv_q - rc_q}, tolerance {qty_tol}). Do not "
                                        "release payment.", "HIGH"))

        po_p, inv_p = _dec_opt(po.get("unit_price")), _dec_opt(inv.get("unit_price"))
        if po_p is None or inv_p is None:
            advisory.append(Finding("price_unverifiable",
                                    f"{tag}: cannot verify unit-price match; PO or invoice unit "
                                    "price is missing.", "MEDI"))
        elif inv_p - po_p > price_tol:
            # Only an overcharge is a violation; billing below PO price is a
            # discount and must pass.
            findings.append(Finding("price_overcharge",
                                    f"{tag}: invoice overcharges (PO ${po_p} vs invoice ${inv_p}); "
                                    f"overcharge ${inv_p - po_p} exceeds tolerance ${price_tol}. "
                                    "Do not release payment.", "HIGH"))

    if findings:
        return CheckResult("THREE_WAY_MATCH", CheckStatus.BLOCK, findings + advisory,
                           method="deterministic")
    if advisory:
        return CheckResult("THREE_WAY_MATCH", CheckStatus.ADVISORY, advisory,
                           method="deterministic")
    return CheckResult("THREE_WAY_MATCH", CheckStatus.PASS, [], method="deterministic")


@register("SEGREGATION_OF_DUTIES", department=_DEPT,
          title="Segregation of duties (requester, approver, receiver)",
          citation="Sarbanes-Oxley Act 404; COSO control activities - segregation of duties")
def check_segregation_of_duties(context: dict) -> CheckResult:
    """No single identity may fill two of the requester / approver / receiver
    roles on the same purchase. Needs ``context['roles']`` =
    {requester, approver, receiver} (or those keys at the top level)."""
    roles = context.get("roles") or {}
    candidates = [
        ("requester", roles.get("requester") or context.get("requester")),
        ("approver", roles.get("approver") or context.get("approver")),
        ("receiver", roles.get("receiver") or roles.get("receipted_by") or context.get("receiver")),
    ]
    present = [(name, _norm(v)) for name, v in candidates if v]
    if not present:
        return CheckResult("SEGREGATION_OF_DUTIES", CheckStatus.NOT_APPLICABLE, [],
                           method="deterministic")
    if len(present) < 2:
        return CheckResult("SEGREGATION_OF_DUTIES", CheckStatus.ADVISORY,
                           [Finding("insufficient_roles",
                                    "Cannot assess separation of duties; fewer than two role "
                                    "holders were identified on this purchase.", "MEDI")],
                           method="deterministic")

    findings: list[Finding] = []
    for i in range(len(present)):
        for j in range(i + 1, len(present)):
            (r1, v1), (r2, v2) = present[i], present[j]
            if v1 == v2:
                findings.append(Finding("sod_conflict",
                                        f"Segregation of duties violation: the same identity is "
                                        f"both {r1} and {r2}; these roles must be held by "
                                        "different people.", "HIGH"))
    status = CheckStatus.BLOCK if findings else CheckStatus.PASS
    return CheckResult("SEGREGATION_OF_DUTIES", status, findings, method="deterministic")


@register("SPEND_AUTHORIZATION", department=_DEPT,
          title="Spend authorization within delegated authority",
          citation="COSO authorization controls; SOX 404 delegation-of-authority matrix")
def check_spend_authorization(context: dict) -> CheckResult:
    """The approved amount must not exceed the approver's delegated authority
    limit. Needs ``context['authorization']`` = {amount, approver_limit,
    approver} (amount/limit may also be top-level ``approval_amount`` /
    ``approver_limit``). Money is Decimal."""
    auth = context.get("authorization") or context.get("spend_authorization") or {}
    amount = auth.get("amount")
    if amount is None:
        amount = context.get("approval_amount") or context.get("invoice_total")
    if amount is None:
        return CheckResult("SPEND_AUTHORIZATION", CheckStatus.NOT_APPLICABLE, [],
                           method="deterministic")
    amt = _dec_opt(amount)
    if amt is None:
        return CheckResult("SPEND_AUTHORIZATION", CheckStatus.ADVISORY,
                           [Finding("bad_amount", "Approval amount is not a parseable number.", "MEDI")],
                           method="deterministic")

    limit = auth.get("approver_limit")
    if limit is None:
        limit = context.get("approver_limit")
    lim = _dec_opt(limit)
    if lim is None:
        return CheckResult("SPEND_AUTHORIZATION", CheckStatus.ADVISORY,
                           [Finding("no_authority_limit",
                                    "No approver authority limit supplied; the approval could not "
                                    "be verified against a delegated limit.", "MEDI")],
                           method="deterministic")

    who = auth.get("approver") or context.get("approver") or "the approver"
    if amt > lim:
        return CheckResult("SPEND_AUTHORIZATION", CheckStatus.BLOCK,
                           [Finding("over_authority",
                                    f"Approved amount ${amt} exceeds {who}'s authority limit "
                                    f"${lim}; escalate to a higher approver.", "HIGH")],
                           method="deterministic")
    return CheckResult("SPEND_AUTHORIZATION", CheckStatus.PASS, [], method="deterministic")


@register("OFAC_SANCTIONS", department=_DEPT,
          title="OFAC / denied-parties sanctions screening",
          citation="OFAC sanctions, 31 CFR Chapter V (Parts 500-599); Executive Order 13224")
def check_ofac_sanctions(context: dict) -> CheckResult:
    """The vendor must not appear on the supplied denied-parties / sanctions
    list. Needs ``context['vendor']`` = {name, id} (or top-level vendor_name /
    vendor_id) and ``context['sanctions_list']`` (or ``denied_parties``) = a
    list of names or {name, id} entries."""
    vendor = context.get("vendor") or {}
    vname = vendor.get("name") or context.get("vendor_name")
    vid = vendor.get("id") or vendor.get("vendor_id") or context.get("vendor_id")
    if not vname and not vid:
        return CheckResult("OFAC_SANCTIONS", CheckStatus.NOT_APPLICABLE, [],
                           method="deterministic")

    sanctions = (context.get("sanctions_list") or context.get("denied_parties")
                 or context.get("ofac_list"))
    if not sanctions:
        return CheckResult("OFAC_SANCTIONS", CheckStatus.ADVISORY,
                           [Finding("no_screening_list",
                                    "No denied-parties / sanctions list supplied; the vendor "
                                    "could not be screened.", "HIGH")],
                           method="deterministic")

    vn = _norm(vname) if vname else None
    vi = _norm(vid) if vid else None
    vn_p = _norm_punct(vname) if vname else None
    vi_p = _norm_punct(vid) if vid else None
    hits: list[str] = []
    near: list[str] = []
    # ponytail: exact normalized match blocks; a punctuation-only difference
    # (LLC vs L.L.C.) is a near match -> ADVISORY. Alias/fuzzy (edit-distance,
    # phonetic) matching is the upgrade path if false-negatives still matter.
    for entry in sanctions:
        if isinstance(entry, dict):
            en = entry.get("name")
            ei = entry.get("id") or entry.get("vendor_id")
        else:
            en, ei = entry, None
        if vn and en and _norm(en) == vn:
            hits.append(str(en))
        elif vi and ei and _norm(ei) == vi:
            hits.append(str(en or ei))
        elif vn_p and en and _norm_punct(en) == vn_p:
            near.append(str(en))
        elif vi_p and ei and _norm_punct(ei) == vi_p:
            near.append(str(en or ei))

    if hits:
        return CheckResult("OFAC_SANCTIONS", CheckStatus.BLOCK,
                           [Finding("sanctioned_vendor",
                                    f"Vendor '{vname or vid}' matches a denied-parties / sanctions "
                                    f"entry ({', '.join(dict.fromkeys(hits))}); payment is "
                                    "prohibited.", "CRIT")],
                           method="deterministic")
    if near:
        return CheckResult("OFAC_SANCTIONS", CheckStatus.ADVISORY,
                           [Finding("possible_sanctioned_vendor",
                                    f"Vendor '{vname or vid}' closely matches a denied-parties / "
                                    f"sanctions entry ({', '.join(dict.fromkeys(near))}) after "
                                    "punctuation normalization; verify before releasing payment.",
                                    "HIGH")],
                           method="deterministic")
    return CheckResult("OFAC_SANCTIONS", CheckStatus.PASS, [], method="deterministic")
