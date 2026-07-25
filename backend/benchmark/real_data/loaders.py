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

# NOTE: pandas/pyarrow are imported LAZILY inside the functions that need them.
# Importing this module must NOT require pandas — CI (and the app runtime) don't
# install it; only the Kaggle-onboarding/benchmark paths (which have the raw data
# and the deps) call the pandas-backed loaders.

RAW_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "kaggle_raw")


def _read_parquet(path: str):
    """Read a parquet file, preferring the pure-Python fastparquet engine.

    Only ever called inside the isolated child process spawned by
    ``load_sales_crm`` (see below) - a fresh interpreter, where both engines
    read reliably. fastparquet is preferred because pyarrow's C extension has
    proven unstable on bleeding-edge builds (CPython 3.14).
    """
    import importlib.util
    import pandas as pd
    engine = "fastparquet" if importlib.util.find_spec("fastparquet") else "auto"
    return pd.read_parquet(path, engine=engine)

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


# Datasets whose loader needs pandas (a benchmark-only dependency that is
# deliberately NOT in requirements.txt). "Available" must mean LOADABLE, not just
# present on disk — otherwise a caller skips nothing and then dies on
# ModuleNotFoundError. Keep in sync with the loaders that `import pandas`.
_PANDAS_BACKED = {"incident_priority", "sales_conversion"}


def available() -> Dict[str, bool]:
    """Which datasets are present locally AND loadable (raw data is gitignored)."""
    import importlib.util

    has_pandas = importlib.util.find_spec("pandas") is not None
    return {
        k: os.path.exists(_path(v["file"])) and (has_pandas or k not in _PANDAS_BACKED)
        for k, v in DATASET_MANIFEST.items()
    }


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
    import pandas as pd
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
    import pandas as pd
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


# ── Relational sales CRM (parquet) — for rich onboarding, not the benchmark ──
# The sales/ dir ships a full relational CRM (accounts <- contacts, leads ->
# opportunities/activities). load_sales_crm returns a coherent, fully-linked
# SUBSET so onboarding can build real Accounts/Contacts/Opportunities/Activities
# instead of a flat lead list.

_SALES_DIR = "sales"
_EMPLOYEE_BAND = {"1-50": 25, "51-200": 120, "200-499": 350, "500-999": 750,
                  "1000-1999": 1500, "2000+": 3000}
_REVENUE_BAND = {"$1M-$10M": 5_000_000, "$10M-$50M": 30_000_000,
                 "$50M-$200M": 125_000_000, "$200M+": 300_000_000}
_OPP_STAGE = {
    "closed_won": ("CLOSED_WON", 100.0), "closed_lost": ("CLOSED_LOST", 0.0),
    "negotiation": ("NEGOTIATION", 75.0), "proposal_sent": ("PROPOSAL", 55.0),
    "demo_completed": ("QUALIFICATION", 35.0), "demo_scheduled": ("QUALIFICATION", 25.0),
}


def sales_crm_available() -> bool:
    """True only if the parquet EXISTS and can actually be read.

    The file alone is not enough: the load needs pandas (a benchmark-only
    dependency that is deliberately NOT in requirements.txt). Probing only the
    path made callers - including the skipif guard in
    tests/test_real_data_loaders.py - believe the data was usable in any
    environment that had the parquet but no pandas, turning a should-skip into a
    hard RuntimeError ("No module named 'pandas'"). Availability must mean
    loadable, not merely present.
    """
    import importlib.util

    if not os.path.exists(_path(f"{_SALES_DIR}/accounts.parquet")):
        return False
    return importlib.util.find_spec("pandas") is not None


def load_sales_crm(account_limit: int | None = None,
                   activity_cap: int = 20000) -> Dict[str, list]:
    """Return a coherent, relationally-linked CRM subset from the sales parquet.

    Runs the ENTIRE load in an isolated child process and returns plain-Python
    dicts via JSON. Rationale: pandas 3's default string arrays are pyarrow-
    backed, and pyarrow's C extension is unstable on bleeding-edge builds
    (CPython 3.14: importing it mid-suite access-violates, poisoning the
    process so that even fastparquet/pandas ops later segfault). A native crash
    cannot be caught in-process; isolating the whole load means a crash
    surfaces as a clean RuntimeError in the parent, and a fresh interpreter
    reads reliably (verified standalone). No date-typed fields cross the
    boundary (consumers use ids/strings/numbers), so JSON is loss-free.
    """
    import json
    import subprocess
    import sys
    import tempfile

    backend_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    child = (
        "import json, os, sys\n"
        "sys.path.insert(0, os.getcwd())\n"
        "from benchmark.real_data.loaders import _load_sales_crm_impl\n"
        "limit = None if sys.argv[1] == 'none' else int(sys.argv[1])\n"
        "result = _load_sales_crm_impl(limit, int(sys.argv[2]))\n"
        "with open(sys.argv[3], 'w', encoding='utf-8') as fh:\n"
        "    json.dump(result, fh, default=str)\n"
    )
    fd, out = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        proc = subprocess.run(
            [sys.executable, "-c", child,
             "none" if account_limit is None else str(account_limit),
             str(activity_cap), out],
            capture_output=True, text=True, timeout=600, cwd=backend_root,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"sales CRM load subprocess failed (exit {proc.returncode}): "
                f"{(proc.stderr or '').strip()[-600:]}"
            )
        with open(out, encoding="utf-8") as fh:
            return json.load(fh)
    finally:
        try:
            os.unlink(out)
        except OSError:
            pass


def _load_sales_crm_impl(account_limit: int | None = None,
                         activity_cap: int = 20000) -> Dict[str, list]:
    """The pandas-backed implementation - only ever run inside the child."""
    base = _path(_SALES_DIR)
    accounts = _read_parquet(f"{base}/accounts.parquet")
    if account_limit:
        accounts = accounts.head(account_limit)
    keep = set(accounts["account_id"].tolist())

    contacts = _read_parquet(f"{base}/contacts.parquet")
    contacts = contacts[contacts["account_id"].isin(keep)]

    leads = _read_parquet(f"{base}/leads.parquet")
    leads = leads[leads["account_id"].isin(keep)]
    lead_to_account = dict(zip(leads["lead_id"], leads["account_id"]))

    opps = _read_parquet(f"{base}/opportunities.parquet")
    opps = opps[opps["lead_id"].isin(lead_to_account.keys())]

    acts = _read_parquet(f"{base}/sales_activities.parquet")
    acts = acts[acts["lead_id"].isin(lead_to_account.keys())].head(activity_cap)

    def _acc_rows():
        for _, r in accounts.iterrows():
            yield {
                "account_id": r["account_id"],
                "company_name": str(r.get("company_name") or f"Account {r['account_id']}"),
                "industry": str(r.get("industry") or "").replace("_", " ").title(),
                "region": str(r.get("region") or ""),
                "employee_count": _EMPLOYEE_BAND.get(str(r.get("employee_band")), 100),
                "arr": float(_REVENUE_BAND.get(str(r.get("estimated_revenue_band")), 1_000_000)),
                "maturity": str(r.get("process_maturity_band") or ""),
            }

    def _contact_rows():
        for _, r in contacts.iterrows():
            yield {
                "contact_id": r["contact_id"], "account_id": r["account_id"],
                "job_title": str(r.get("job_title") or "Contact"),
                "seniority": str(r.get("seniority") or ""),
                "buyer_role": str(r.get("buyer_role") or ""),
                "email_domain_type": str(r.get("email_domain_type") or "corporate"),
            }

    def _opp_rows():
        for _, r in opps.iterrows():
            stage, prob = _OPP_STAGE.get(str(r.get("stage")), ("PROSPECTING", 10.0))
            yield {
                "opportunity_id": r["opportunity_id"],
                "account_id": lead_to_account[r["lead_id"]],
                "stage": stage, "probability": prob,
                "amount": float(r.get("estimated_acv") or 0),
                "created_at": r.get("created_at"),
            }

    def _activity_rows():
        for _, r in acts.iterrows():
            yield {
                "account_id": lead_to_account[r["lead_id"]],
                "activity_type": str(r.get("activity_type") or "task").upper(),
                "outcome": str(r.get("activity_outcome") or ""),
                "timestamp": r.get("activity_timestamp"),
            }

    return {
        "accounts": list(_acc_rows()),
        "contacts": list(_contact_rows()),
        "opportunities": list(_opp_rows()),
        "activities": list(_activity_rows()),
    }


def load_procurement_orders(limit: int | None = None) -> Iterator[Dict[str, Any]]:
    """Raw procurement POs (keeps PO_ID + Supplier) for building real purchase
    orders and vendors — richer than load_procurement_compliance (which drops them)."""
    def _num(x):
        try:
            return float(x)
        except (ValueError, TypeError):
            return 0.0
    for r in _read_csv(DATASET_MANIFEST["procurement_compliance"]["file"], limit):
        yield {
            "po_id": r.get("PO_ID", ""),
            "supplier": r.get("Supplier", "").strip() or "Unknown Supplier",
            "item_category": r.get("Item_Category", ""),
            "order_status": r.get("Order_Status", ""),
            "quantity": int(_num(r.get("Quantity"))),
            "unit_price": _num(r.get("Unit_Price")),
            "negotiated_price": _num(r.get("Negotiated_Price")),
            "defective_units": int(_num(r.get("Defective_Units"))),
            "compliant": (r.get("Compliance") or "").strip() == "Yes",
        }


LOADERS = {
    "hr_attrition": load_hr_attrition,
    "support_priority": load_support_priority,
    "incident_priority": load_incident_priority,
    "sales_conversion": load_sales_conversion,
    "procurement_compliance": load_procurement_compliance,
    "finance_late_payment": load_finance_late_payment,
    "legal_clause_type": load_legal_clause_type,
}
