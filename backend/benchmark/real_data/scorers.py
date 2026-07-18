"""
Real-data benchmark — KAEOS domain scorers.

Each scorer is KAEOS's DETERMINISTIC classification logic for one domain: the
rule-based path the agents fall back to when the LLM is weak or unavailable.
That path is exactly what makes KAEOS safe under BYOK (a poor model routes to
these rules + a human), so measuring it against real recorded outcomes is a
genuine test of product logic — no LLM, fully reproducible.

Each returns (prediction, confidence). The runner compares prediction to the
recorded human outcome and also checks the confidence→HITL behavior: low
confidence should correlate with the cases KAEOS gets wrong (i.e. it knows what
it doesn't know and escalates them).
"""
from __future__ import annotations

from typing import Any, Dict, Tuple

# The production HITL threshold. Below this, KAEOS routes a decision to a human.
HITL_THRESHOLD = 0.82


# ── HR: attrition-risk classifier ────────────────────────────────────────────

def score_hr_attrition(f: Dict[str, Any]) -> Tuple[bool, float]:
    """
    Flag flight risk from engagement signals. Mirrors the weighting an HR
    retention agent applies: low satisfaction, overtime, stalled promotion, and
    low equity are the classic attrition drivers.
    """
    risk = 0.0
    risk += (4 - f["job_satisfaction"]) * 0.10
    risk += (4 - f["environment_satisfaction"]) * 0.07
    risk += (4 - f["work_life_balance"]) * 0.07
    risk += (4 - f["job_involvement"]) * 0.08
    if f["overtime"]:
        risk += 0.22
    if f["years_since_promotion"] >= 5:
        risk += 0.12
    if f["stock_option_level"] == 0:
        risk += 0.12
    if f["years_at_company"] <= 2:
        risk += 0.10
    if f["monthly_income"] < 3000:
        risk += 0.10

    # Attrition is a rare event (~16% base rate), so only a strong confluence of
    # drivers should flag flight risk. A low bar floods the queue with false
    # positives — worse than not flagging at all.
    threshold = 0.75
    predicted = risk >= threshold
    confidence = min(1.0, 0.5 + abs(risk - threshold))
    return predicted, round(confidence, 3)


# ── Support: ticket-priority classifier ──────────────────────────────────────

_URGENT_WORDS = ("urgent", "asap", "immediately", "critical", "down", "outage",
                 "cannot access", "can't access", "not working", "broken", "data loss",
                 "security", "breach", "refund", "charged twice", "double charged")
_HIGH_WORDS = ("error", "fail", "unable", "issue", "problem", "bug", "crash", "500")
_LOW_WORDS = ("how to", "question", "request", "documentation", "guide", "feature",
              "cancel", "billing inquiry", "when will")


def score_support_priority(f: Dict[str, Any]) -> Tuple[str, float]:
    """Classify priority from ticket text — keyword severity signals."""
    text = f"{f.get('ticket_type','')} {f.get('subject','')} {f.get('description','')}".lower()
    urgent = sum(w in text for w in _URGENT_WORDS)
    high = sum(w in text for w in _HIGH_WORDS)
    low = sum(w in text for w in _LOW_WORDS)

    if urgent >= 2:
        return "Critical", 0.85
    if urgent == 1:
        return "High", 0.7
    if high >= 1 and low == 0:
        return "High", 0.6
    if low >= 1 and high == 0:
        return "Low", 0.65
    return "Medium", 0.5


# ── Engineering: incident priority from the ITIL impact×urgency matrix ────────

_LEVEL = {"1 - High": 1, "2 - Medium": 2, "3 - Low": 3,
          "1 - Critical": 1, "1": 1, "2": 2, "3": 3}


def score_incident_priority(f: Dict[str, Any]) -> Tuple[str, float]:
    """
    Derive incident priority from impact and urgency using the standard ITIL
    matrix — the same reasoning KAEOS's incident agent applies. Measured against
    the priority the real ServiceNow instance recorded.
    """
    i = _LEVEL.get(f["impact"], 2)
    u = _LEVEL.get(f["urgency"], 2)
    # ServiceNow default priority matrix (impact rows, urgency cols).
    matrix = {
        (1, 1): "1 - Critical", (1, 2): "2 - High", (1, 3): "3 - Moderate",
        (2, 1): "2 - High", (2, 2): "3 - Moderate", (2, 3): "4 - Low",
        (3, 1): "3 - Moderate", (3, 2): "4 - Low", (3, 3): "4 - Low",
    }
    pred = matrix.get((i, u), "3 - Moderate")
    # High confidence when impact and urgency agree, lower when they diverge.
    confidence = 0.9 if i == u else 0.7
    return pred, confidence


def score_incident_sla_breach(f: Dict[str, Any]) -> Tuple[bool, float]:
    """
    Predict SLA breach risk from operational churn. KAEOS treats reassignment and
    reopen churn as the leading indicators of a miss — the same signal the deploy
    /incident risk agents weight. Measured against real made_sla=false.
    """
    churn = f.get("reassignment_count", 0) + f.get("reopen_count", 0) * 2
    predicted_breach = churn >= 3
    confidence = min(1.0, 0.55 + churn * 0.08)
    return predicted_breach, round(confidence, 3)


# ── Sales: lead-conversion classifier ────────────────────────────────────────

_SENIOR = ("c-level", "vp", "director", "head", "chief", "owner", "founder")


def score_sales_conversion(f: Dict[str, Any]) -> Tuple[bool, float]:
    """Score lead conversion likelihood from engagement + buyer fit."""
    score = 0.0
    score += min(0.35, f.get("touch_count", 0) * 0.05)
    score += min(0.20, f.get("inbound_touch_count", 0) * 0.08)
    score += min(0.20, f.get("activity_count", 0) * 0.04)
    if any(s in f.get("seniority", "").lower() for s in _SENIOR):
        score += 0.12
    if f.get("buyer_role", "").lower() in ("decision_maker", "economic_buyer", "champion"):
        score += 0.12
    if f.get("process_maturity_band") == "high":
        score += 0.10

    threshold = 0.55
    predicted = score >= threshold
    confidence = min(1.0, 0.5 + abs(score - threshold))
    return predicted, round(confidence, 3)


# ── Operations: procurement compliance classifier ────────────────────────────

def score_procurement_compliance(f: Dict[str, Any]) -> Tuple[bool, float]:
    """
    Predict whether a purchase order is compliant. Cancelled/defective orders and
    prices that ignore the negotiated rate are the non-compliance signals.
    """
    risk = 0.0
    if f.get("order_status") == "Cancelled":
        risk += 0.4
    if f.get("defective_units", 0) > 0:
        risk += 0.3
    unit, neg = f.get("unit_price", 0), f.get("negotiated_price", 0)
    if neg and unit and unit > neg * 1.15:
        risk += 0.3  # paid well above the negotiated price

    predicted_compliant = risk < 0.4
    confidence = min(1.0, 0.55 + abs(risk - 0.4))
    return predicted_compliant, round(confidence, 3)


# ── Finance: invoice late-payment classifier ─────────────────────────────────

def score_finance_late_payment(f: Dict[str, Any]) -> Tuple[bool, float]:
    """
    Predict whether an invoice settles past its due date — the call an AR
    collections agent makes when deciding which invoices to chase. Signals, in
    order of strength (measured on this dataset): the customer's own prior
    late rate, an open dispute, and paper (vs electronic) billing.

    Uses ONLY information available while the invoice is open. The outcome
    fields the loader carries for onboarding (days_late, settled_date,
    days_to_settle) are off-limits here.
    """
    risk = 0.0
    prior_rate = f.get("prior_late_rate")
    prior_n = f.get("prior_invoice_count", 0)
    if prior_rate is not None and prior_n >= 3:
        # Payment behavior is habitual: weight history most.
        risk += prior_rate * 0.55
    else:
        # No usable history: fall back to the population base rate (~36%).
        risk += 0.36 * 0.55
    if f.get("disputed"):
        risk += 0.30
    if f.get("paper_billing"):
        risk += 0.10
    if f.get("invoice_amount", 0) > 90:
        risk += 0.05

    threshold = 0.50
    predicted_late = risk >= threshold
    # History depth makes the call more trustworthy; thin history caps confidence.
    confidence = min(1.0, 0.45 + abs(risk - threshold) + min(prior_n, 10) * 0.02)
    return predicted_late, round(confidence, 3)


# ── Legal: contract clause-type classifier (CUAD categories) ─────────────────
#
# Ordered most-specific-first: the first rule whose patterns hit wins. A real
# legal-review agent works the same way — unmistakable phrases ("liquidated
# damages", "right of first refusal") decide instantly; generic language falls
# through to weaker rules; no hit at all routes to a human (low confidence).
_CLAUSE_RULES: Tuple[Tuple[str, Tuple[str, ...], float], ...] = (
    ("Liquidated Damages", ("liquidated damages",), 0.95),
    ("Source Code Escrow", ("escrow",), 0.9),
    ("Most Favored Nation", ("most favored", "no less favorable", "at least as favorable",
                             "as favorable as"), 0.9),
    ("Third Party Beneficiary", ("third party beneficiar", "third-party beneficiar"), 0.9),
    ("Non-Disparagement", ("disparag",), 0.9),
    ("Covenant Not To Sue", ("covenant not to sue", "agrees not to sue", "shall not sue",
                             "not to institute", "shall not bring any", "waives any claim"), 0.9),
    ("Rofr/Rofo/Rofn", ("right of first refusal", "right of first offer",
                        "right of first negotiation", "first right to"), 0.9),
    ("Change Of Control", ("change of control", "change in control"), 0.9),
    ("No-Solicit Of Employees", ("solicit any employee", "solicit or hire", "hire any employee",
                                 "solicit for employment", "solicit any of the employees"), 0.85),
    ("No-Solicit Of Customers", ("solicit any customer", "solicit customers",
                                 "solicit any client", "solicit business from"), 0.85),
    ("Joint Ip Ownership", ("jointly own", "joint ownership", "jointly-owned", "owned jointly"), 0.85),
    ("Termination For Convenience", ("for convenience", "terminate this agreement at any time",
                                     "terminate at any time without cause",
                                     "terminate this agreement without cause"), 0.85),
    ("Notice Period To Terminate Renewal", ("notice of non-renewal", "notice of its intention not to renew",
                                            "written notice of termination prior to"), 0.8),
    ("Uncapped Liability", ("unlimited liability", "liability shall be unlimited",
                            "shall not be subject to any limitation", "without limitation of liability"), 0.8),
    ("Cap On Liability", ("liability shall not exceed", "liability is limited to",
                          "in no event shall", "aggregate liability", "shall not be liable for any indirect",
                          "consequential damages", "limitation of liability"), 0.8),
    ("Insurance", ("insurance", "insurer", "policy of insurance", "coverage limits"), 0.85),
    ("Audit Rights", ("audit", "inspect the books", "examine the records", "right to inspect"), 0.85),
    ("Governing Law", ("governed by", "governing law", "construed in accordance with the laws"), 0.9),
    ("Anti-Assignment", ("shall not assign", "may not assign", "not assignable",
                         "shall not be assigned", "may not be assigned", "without the prior written consent"), 0.75),
    ("Warranty Duration", ("warranty period", "warrants that", "warranty shall"), 0.7),
    ("Irrevocable Or Perpetual License", ("irrevocable", "perpetual"), 0.8),
    ("Non-Transferable License", ("non-transferable", "nontransferable"), 0.85),
    ("Unlimited/All-You-Can-Eat-License", ("unlimited license", "unlimited right"), 0.75),
    ("Affiliate License-Licensee", ("affiliates of licensee", "licensee and its affiliates",
                                    "licensee's affiliates"), 0.7),
    ("Affiliate License-Licensor", ("affiliates of licensor", "licensor and its affiliates",
                                    "licensor's affiliates"), 0.7),
    ("License Grant", ("hereby grants", "grants to", "grant of license", "license to use",
                       "licensed to"), 0.75),
    ("Ip Ownership Assignment", ("assigns all right, title", "hereby assigns", "work made for hire",
                                 "ownership of all intellectual property", "shall own all"), 0.75),
    ("Source Code Escrow", ("source code",), 0.6),
    ("Non-Compete", ("shall not compete", "not to compete", "non-compete", "noncompete",
                     "competing product", "competitive business"), 0.75),
    ("Competitive Restriction Exception", ("except that", "notwithstanding the foregoing"), 0.4),
    ("Exclusivity", ("exclusive", "exclusivity", "solely and exclusively"), 0.7),
    ("Volume Restriction", ("maximum quantity", "volume limit", "not to exceed", "maximum number of"), 0.6),
    ("Minimum Commitment", ("minimum", "at least", "no less than", "shall purchase"), 0.6),
    ("Revenue/Profit Sharing", ("royalt", "revenue shar", "profit shar", "percentage of net",
                                "percentage of gross", "commission"), 0.75),
    ("Price Restrictions", ("price increase", "pricing", "price shall not"), 0.55),
    ("Renewal Term", ("renew", "renewal term", "automatically extend"), 0.7),
    ("Post-Termination Services", ("after termination", "following termination", "upon termination",
                                   "post-termination", "after the expiration"), 0.6),
)

# What the classifier answers when nothing matches — routed to a human.
CLAUSE_UNCLASSIFIED = "Unclassified"


def score_legal_clause_type(f: Dict[str, Any]) -> Tuple[str, float]:
    """
    Classify a contract clause into its CUAD category from characteristic
    phrases. First specific rule wins; a clause matching many rules is genuinely
    ambiguous, so confidence drops with the number of competing hits; no hit
    returns Unclassified at low confidence (below HITL_THRESHOLD — a human reads it).
    """
    text = f.get("clause_text", "").lower()
    if not text:
        return CLAUSE_UNCLASSIFIED, 0.3

    matches = [
        (category, base_conf)
        for category, patterns, base_conf in _CLAUSE_RULES
        if any(p in text for p in patterns)
    ]
    if not matches:
        return CLAUSE_UNCLASSIFIED, 0.3

    category, base_conf = matches[0]
    ambiguity_penalty = 0.05 * (len(matches) - 1)
    return category, round(max(0.35, base_conf - ambiguity_penalty), 3)


SCORERS = {
    "hr_attrition": ("binary", score_hr_attrition),
    "support_priority": ("multiclass", score_support_priority),
    "incident_priority": ("multiclass", None),          # handled specially (nested GT)
    "sales_conversion": ("binary", score_sales_conversion),
    "procurement_compliance": ("binary", score_procurement_compliance),
    "finance_late_payment": ("binary", score_finance_late_payment),
    "legal_clause_type": ("multiclass", score_legal_clause_type),
}
