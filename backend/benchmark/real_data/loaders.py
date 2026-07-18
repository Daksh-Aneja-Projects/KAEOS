"""
Real-data benchmark — dataset loaders.

Each loader reads a raw Kaggle dataset (downloaded to backend/data/kaggle_raw/,
gitignored) and yields rows in a common shape:

    {"features": {...}, "ground_truth": <recorded human outcome>}

The raw data is NOT committed — it is licensed and large. The manifest below
records exactly which dataset each domain came from so the benchmark is
reproducible: re-download with the same refs and re-run.
"""
from __future__ import annotations

import csv
import os
from typing import Any, Dict, Iterator, List

import pandas as pd

RAW_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "kaggle_raw")

# Provenance — the exact source of every domain's real data.
DATASET_MANIFEST = {
    "hr_attrition": {
        "kaggle_ref": "pavansubhasht/ibm-hr-analytics-attrition-dataset",
        "file": "hr/WA_Fn-UseC_-HR-Employee-Attrition.csv",
        "rows": 1470,
        "ground_truth": "Attrition (Yes/No) — did this employee actually leave",
        "kaeos_domain": "hr",
    },
    "support_priority": {
        "kaggle_ref": "suraj520/customer-support-ticket-dataset",
        "file": "support/customer_support_tickets.csv",
        "rows": 8469,
        "ground_truth": "Ticket Priority (Critical/High/Medium/Low) assigned by support staff",
        "kaeos_domain": "support",
    },
    "incident_priority": {
        "kaggle_ref": "shamiulislamshifat/it-incident-log-dataset",
        "file": "incidents/incident_event_log.csv",
        "rows": 141712,
        "ground_truth": "priority (1-Critical..4-Low) + made_sla — a real ServiceNow instance",
        "kaeos_domain": "engineering",
    },
    "sales_conversion": {
        "kaggle_ref": "derelictpanda/leadforge-lead-scoring-intro-v1",
        "file": "sales/lead_scoring.csv",
        "rows": 5000,
        "ground_truth": "converted_within_90_days — did the lead actually convert",
        "kaeos_domain": "sales",
    },
    "procurement_compliance": {
        "kaggle_ref": "shahriarkabir/procurement-kpi-analysis-dataset",
        "file": "procurement/Procurement KPI Analysis Dataset.csv",
        "rows": 777,
        "ground_truth": "Compliance (Yes/No) of the purchase order",
        "kaeos_domain": "operations",
    },
    "finance_late_payment": {
        "kaggle_ref": "hhenry/finance-factoring-ibm-late-payment-histories",
        "file": "finance/WA_Fn-UseC_-Accounts-Receivable.csv",
        "rows": 2466,
        "ground_truth": "DaysLate > 0 — was the invoice actually settled after its due date",
        "kaeos_domain": "finance",
    },
    "legal_clause_type": {
        "kaggle_ref": "konradb/atticus-open-contract-dataset-aok-beta",
        "file": "legal/CUAD_v1.json",
        "rows": 9358,  # substantive clause spans (metadata categories excluded)
        "ground_truth": "Clause category assigned by Atticus Project legal experts (CUAD v1)",
        "kaeos_domain": "legal",
    },
}


def _path(rel: str) -> str:
    return os.path.join(RAW_DIR, rel)


def available() -> Dict[str, bool]:
    """Which datasets are present locally (raw data is gitignored)."""
    return {k: os.path.exists(_path(v["file"])) for k, v in DATASET_MANIFEST.items()}


def _read_csv(rel: str, limit: int | None = None) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(_path(rel), encoding="utf-8-sig") as f:
        for i, row in enumerate(csv.DictReader(f)):
            if limit and i >= limit:
                break
            rows.append(row)
    return rows


def load_hr_attrition(limit: int | None = None) -> Iterator[Dict[str, Any]]:
    for r in _read_csv(DATASET_MANIFEST["hr_attrition"]["file"], limit):
        yield {
            "features": {
                "job_satisfaction": int(r["JobSatisfaction"]),
                "environment_satisfaction": int(r["EnvironmentSatisfaction"]),
                "work_life_balance": int(r["WorkLifeBalance"]),
                "job_involvement": int(r["JobInvolvement"]),
                "overtime": r["OverTime"] == "Yes",
                "years_at_company": int(r["YearsAtCompany"]),
                "years_since_promotion": int(r["YearsSinceLastPromotion"]),
                "monthly_income": int(r["MonthlyIncome"]),
                "stock_option_level": int(r["StockOptionLevel"]),
                "job_role": r["JobRole"],
            },
            "ground_truth": r["Attrition"] == "Yes",
        }


def load_support_priority(limit: int | None = None) -> Iterator[Dict[str, Any]]:
    for r in _read_csv(DATASET_MANIFEST["support_priority"]["file"], limit):
        gt = (r.get("Ticket Priority") or "").strip()
        if not gt:
            continue
        yield {
            "features": {
                "ticket_type": r.get("Ticket Type", ""),
                "subject": r.get("Ticket Subject", ""),
                "description": r.get("Ticket Description", ""),
                "product": r.get("Product Purchased", ""),
            },
            "ground_truth": gt,   # Critical | High | Medium | Low
        }


def load_incident_priority(limit: int | None = None) -> Iterator[Dict[str, Any]]:
    # 141k rows; use pandas + sampling for speed and to dedupe event rows.
    df = pd.read_csv(_path(DATASET_MANIFEST["incident_priority"]["file"]),
                     usecols=["number", "impact", "urgency", "priority", "made_sla",
                              "reassignment_count", "reopen_count", "category"],
                     nrows=limit * 20 if limit else None)
    # One row per incident (last event carries the resolved state).
    df = df.drop_duplicates(subset=["number"], keep="last")
    if limit:
        df = df.head(limit)
    for _, r in df.iterrows():
        impact = str(r["impact"])
        urgency = str(r["urgency"])
        priority = str(r["priority"])
        if "?" in (impact + urgency + priority):
            continue
        yield {
            "features": {
                "impact": impact,          # "1 - High" etc.
                "urgency": urgency,
                "reassignment_count": int(r["reassignment_count"]) if pd.notna(r["reassignment_count"]) else 0,
                "reopen_count": int(r["reopen_count"]) if pd.notna(r["reopen_count"]) else 0,
                "category": str(r["category"]),
            },
            "ground_truth": {
                "priority": priority,               # "1 - Critical" etc.
                "made_sla": str(r["made_sla"]).lower() == "true",
            },
        }


def load_sales_conversion(limit: int | None = None) -> Iterator[Dict[str, Any]]:
    df = pd.read_csv(_path(DATASET_MANIFEST["sales_conversion"]["file"]), nrows=limit)
    for _, r in df.iterrows():
        yield {
            "features": {
                "touch_count": float(r.get("touch_count", 0) or 0),
                "inbound_touch_count": float(r.get("inbound_touch_count", 0) or 0),
                "activity_count": float(r.get("activity_count", 0) or 0),
                "seniority": str(r.get("seniority", "")),
                "buyer_role": str(r.get("buyer_role", "")),
                "process_maturity_band": str(r.get("process_maturity_band", "")),
                "employee_band": str(r.get("employee_band", "")),
            },
            "ground_truth": bool(r.get("converted_within_90_days", False)),
        }


def load_procurement_compliance(limit: int | None = None) -> Iterator[Dict[str, Any]]:
    for r in _read_csv(DATASET_MANIFEST["procurement_compliance"]["file"], limit):
        gt = (r.get("Compliance") or "").strip()
        if not gt:
            continue
        def _num(x):
            try:
                return float(x)
            except (ValueError, TypeError):
                return 0.0
        yield {
            "features": {
                "order_status": r.get("Order_Status", ""),
                "quantity": _num(r.get("Quantity")),
                "unit_price": _num(r.get("Unit_Price")),
                "negotiated_price": _num(r.get("Negotiated_Price")),
                "defective_units": _num(r.get("Defective_Units")),
                "item_category": r.get("Item_Category", ""),
            },
            "ground_truth": gt == "Yes",
        }


def load_finance_late_payment(limit: int | None = None) -> Iterator[Dict[str, Any]]:
    """
    IBM factoring invoice histories — predict whether an invoice settles late.

    The strongest legitimate signal a collections agent has is the customer's
    own payment history, so each row carries the customer's prior-invoice late
    rate computed over invoices dated STRICTLY BEFORE this one (chronological
    order, no leakage from the future or from the row's own outcome).
    """
    from datetime import datetime as _dt

    def _date(s: str):
        return _dt.strptime(s.strip(), "%m/%d/%Y")

    rows = _read_csv(DATASET_MANIFEST["finance_late_payment"]["file"])
    rows.sort(key=lambda r: _date(r["InvoiceDate"]))

    history: Dict[str, List[bool]] = {}
    emitted = 0
    for r in rows:
        if limit and emitted >= limit:
            break
        try:
            late = int(r["DaysLate"]) > 0
            amount = float(r["InvoiceAmount"])
        except (ValueError, TypeError):
            continue
        cust = r["customerID"]
        prior = history.setdefault(cust, [])
        yield {
            "features": {
                "customer_id": cust,
                "country_code": r.get("countryCode", ""),
                "invoice_number": r.get("invoiceNumber", ""),
                "invoice_date": r.get("InvoiceDate", ""),
                "due_date": r.get("DueDate", ""),
                "settled_date": r.get("SettledDate", ""),
                "invoice_amount": amount,
                "disputed": r.get("Disputed") == "Yes",
                "paper_billing": r.get("PaperlessBill") == "Paper",
                "prior_invoice_count": len(prior),
                "prior_late_rate": (sum(prior) / len(prior)) if prior else None,
                # OUTCOME fields — carried for onboarding (real settled dates),
                # NEVER to be read by a scorer: they ARE the ground truth.
                "days_to_settle": int(r["DaysToSettle"]),
                "days_late": int(r["DaysLate"]),
            },
            "ground_truth": late,
        }
        prior.append(late)
        emitted += 1


# CUAD annotates 41 categories; five are document metadata (who signed, when),
# which is an extraction task, not clause-risk classification. The benchmark
# scores the 36 substantive categories a legal-review agent actually classifies.
CUAD_METADATA_CATEGORIES = {
    "Document Name", "Parties", "Agreement Date", "Effective Date", "Expiration Date",
}


def load_legal_clause_type(limit: int | None = None) -> Iterator[Dict[str, Any]]:
    """
    CUAD v1 — 510 real commercial contracts, clause spans labelled by Atticus
    Project legal experts. Each row is one expert-extracted clause span; ground
    truth is the category the experts assigned it.
    """
    import json as _json

    with open(_path(DATASET_MANIFEST["legal_clause_type"]["file"]), encoding="utf-8") as f:
        data = _json.load(f)["data"]

    def _contract_type(title: str) -> str:
        # Titles look like "LIMEENERGYCO_09_09_1999-EX-10-DISTRIBUTOR AGREEMENT";
        # the trailing dash segment is the SEC exhibit's agreement type.
        tail = title.rsplit("-", 1)[-1].strip()
        return tail if tail and not tail[0].isdigit() else "AGREEMENT"

    emitted = 0
    for contract in data:
        title = contract["title"]
        for qa in contract["paragraphs"][0]["qas"]:
            category = qa["id"].split("__")[-1].strip()
            if category in CUAD_METADATA_CATEGORIES:
                continue
            for ans in qa["answers"]:
                text = (ans.get("text") or "").strip()
                if not text:
                    continue
                if limit and emitted >= limit:
                    return
                yield {
                    "features": {
                        "clause_text": text,
                        "contract_title": title,
                        "contract_type": _contract_type(title),
                    },
                    "ground_truth": category,
                }
                emitted += 1


LOADERS = {
    "hr_attrition": load_hr_attrition,
    "support_priority": load_support_priority,
    "incident_priority": load_incident_priority,
    "sales_conversion": load_sales_conversion,
    "procurement_compliance": load_procurement_compliance,
    "finance_late_payment": load_finance_late_payment,
    "legal_clause_type": load_legal_clause_type,
}
