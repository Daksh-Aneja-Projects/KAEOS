"""
KAEOS — Onboard a Real Company from real enterprise datasets.

This is the "onboard a client" scenario: take real, human-authored enterprise
data (from Kaggle, downloaded to data/kaggle_raw/) and load it into KAEOS as a
single coherent tenant — "RealCo, Inc." — so every domain renders REAL records
instead of synthetic seed data, and the Company Brain ingests real Signals.

It maps:
  IBM HR Attrition        -> HR employees (real roles, satisfaction, tenure)
  Customer support tickets-> Support tickets (real subjects, descriptions)
  ServiceNow incident log -> Engineering incidents (real impact/urgency/priority)
  LeadForge lead scoring  -> Sales leads (real engagement, conversion)
  Procurement KPI         -> Operations purchase requests (real suppliers, POs)
  IBM AR Late Payments    -> Finance customers + AR invoices (real amounts, real settle dates)
  CUAD v1 contracts       -> Legal contracts + expert-labelled clauses (real SEC-filed text)

Every record also becomes a Signal with a source-appropriate authority score,
so the same data feeds the knowledge/confidence layer.

Idempotent: clears and reloads the RealCo tenant on each run.

Usage:
    cd backend && python -m scripts.onboard_real_company [--limit N]
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete

# Onboarding is maintenance: it writes rows for a tenant it is creating, so
# it runs on the OWNER connection (RLS exempt). Going through the app role
# would be blocked - correctly - for having no tenant context.
from app.core.database import MaintenanceSessionLocal as AsyncSessionLocal, init_db
from benchmark.real_data import loaders

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("onboard")

TENANT = "tenant_realco"
COMPANY = "RealCo, Inc."


def _id() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _clear(session):
    """Remove any prior RealCo data so onboarding is idempotent."""
    from app.hr.models.core import HREmployee
    from app.support.models.tickets import Ticket
    from app.engineering.models.incidents import Incident
    from app.sales.models.leads import Lead
    from app.models.domain import Signal
    from app.finance.models.accounts_receivable import Customer, CustomerInvoice
    from app.legal.models.contracts import Contract, ContractClause

    # Children before parents (ContractClause -> Contract, CustomerInvoice -> Customer).
    for model in (HREmployee, Ticket, Incident, Lead, Signal,
                  ContractClause, Contract, CustomerInvoice, Customer):
        await session.execute(delete(model).where(model.tenant_id == TENANT))
    await session.commit()


def _signal(domain: str, source: str, entity: str, payload: str, authority: float, pii: bool):
    from app.models.domain import Signal
    return Signal(
        id=_id(), tenant_id=TENANT, source_type=source, source_entity=entity,
        signal_type="ONBOARDED_RECORD", domain=domain, clean_payload=payload[:1000],
        authority_score=authority, novelty_score=0.5, pii_present=pii, created_at=_now(),
    )


async def onboard_hr(session, limit: int) -> tuple[int, int]:
    from app.hr.models.core import HREmployee, EmploymentStatus
    n_emp = n_sig = 0
    for i, row in enumerate(loaders.load_hr_attrition(limit=limit)):
        f = row["features"]
        left = row["ground_truth"]
        first = f["job_role"].split()[0] + str(i)
        emp = HREmployee(
            id=_id(), tenant_id=TENANT, worker_id=f"RC-EMP-{i:04d}",
            first_name=first, last_name="(RealCo)",
            email=f"emp{i}@realco.example", job_title=f["job_role"],
            status=EmploymentStatus.TERMINATED if left else EmploymentStatus.ACTIVE,
            hire_date=date.today() - timedelta(days=365 * max(1, f["years_at_company"])),
            termination_date=date.today() - timedelta(days=30) if left else None,
            location="Remote", is_remote=True,
        )
        session.add(emp)
        n_emp += 1
        session.add(_signal(
            "hr", "HRIS", f"employee:{emp.worker_id}",
            f"{f['job_role']} — satisfaction {f['job_satisfaction']}/4, "
            f"tenure {f['years_at_company']}y, overtime={f['overtime']}, "
            f"outcome={'LEFT' if left else 'retained'}",
            authority=0.95, pii=True))
        n_sig += 1
    await session.commit()
    return n_emp, n_sig


async def onboard_support(session, limit: int) -> tuple[int, int]:
    from app.support.models.tickets import Ticket, TicketPriority, TicketStatus
    pmap = {"Critical": TicketPriority.URGENT, "High": TicketPriority.HIGH,
            "Medium": TicketPriority.MEDIUM, "Low": TicketPriority.LOW}
    n_t = n_sig = 0
    for i, row in enumerate(loaders.load_support_priority(limit=limit)):
        f = row["features"]
        t = Ticket(
            id=_id(), tenant_id=TENANT, ticket_number=f"RC-TKT-{i:05d}",
            customer_id=f"CUST-{i % 500}",
            subject=(f["subject"] or f["ticket_type"] or "Support request")[:255],
            description=(f["description"] or "")[:2000] or "Imported from support log.",
            priority=pmap.get(row["ground_truth"], TicketPriority.MEDIUM),
            status=TicketStatus.NEW,
        )
        session.add(t)
        n_t += 1
        session.add(_signal(
            "support", "HELPDESK", f"ticket:{t.ticket_number}",
            f"[{row['ground_truth']}] {t.subject}", authority=0.75, pii=True))
        n_sig += 1
    await session.commit()
    return n_t, n_sig


async def onboard_engineering(session, limit: int) -> tuple[int, int]:
    from app.engineering.models.incidents import Incident, IncidentSeverity, IncidentStatus
    sev = {"1 - Critical": IncidentSeverity.SEV1, "2 - High": IncidentSeverity.SEV2,
           "3 - Moderate": IncidentSeverity.SEV3, "4 - Low": IncidentSeverity.SEV4}
    n_i = n_sig = 0
    for i, row in enumerate(loaders.load_incident_priority(limit=limit)):
        f = row["features"]
        gt = row["ground_truth"]
        inc = Incident(
            id=_id(), tenant_id=TENANT, incident_number=f"RC-INC-{i:05d}",
            title=f"{f['category']} incident"[:255],
            description=f"impact={f['impact']}, urgency={f['urgency']}, "
                        f"reassignments={f['reassignment_count']}, reopens={f['reopen_count']}",
            severity=sev.get(gt["priority"], IncidentSeverity.SEV3),
            status=IncidentStatus.RESOLVED if gt["made_sla"] else IncidentStatus.MITIGATING,
            detected_by="ALERT",
            customer_impacting=gt["priority"].startswith(("1", "2")),
            # Approximate blast radius from the recorded priority so downstream
            # severity assessment has a realistic user-impact signal.
            affected_users={"1": 5000, "2": 800, "3": 80, "4": 5}.get(gt["priority"][0], 50),
        )
        session.add(inc)
        n_i += 1
        session.add(_signal(
            "engineering", "ITSM", f"incident:{inc.incident_number}",
            f"[{gt['priority']}] {f['category']} — made_sla={gt['made_sla']}, "
            f"churn={f['reassignment_count']}/{f['reopen_count']}",
            authority=0.95, pii=False))
        n_sig += 1
    await session.commit()
    return n_i, n_sig


async def onboard_sales(session, limit: int) -> tuple[int, int]:
    from app.sales.models.leads import Lead
    n_l = n_sig = 0
    for i, row in enumerate(loaders.load_sales_conversion(limit=limit)):
        f = row["features"]
        converted = row["ground_truth"]
        # source is a LeadSource ENUM - raw dataset roles must map onto it.
        # (SQLite accepts any string on insert; SQLAlchemy raises on read.)
        role_to_source = {
            "champion": "REFERRAL",
            "economic_buyer": "OUTBOUND",
            "end_user": "WEBSITE",
            "technical_evaluator": "CONFERENCE",
        }
        lead = Lead(
            id=_id(), tenant_id=TENANT,
            company=f"Prospect {i} ({f.get('employee_band','')})"[:255],
            contact_name=f"{f.get('seniority','contact')} ({f.get('buyer_role','contact')}) {i}",
            email=f"lead{i}@prospect.example",
            source=role_to_source.get(f.get("buyer_role"), "WEBSITE"),
            is_converted=converted,
        )
        session.add(lead)
        n_l += 1
        session.add(_signal(
            "sales", "CRM", f"lead:{i}",
            f"{f.get('seniority')} / {f.get('buyer_role')} — touches {f.get('touch_count')}, "
            f"outcome={'CONVERTED' if converted else 'open'}",
            authority=0.8, pii=True))
        n_sig += 1
    await session.commit()
    return n_l, n_sig


async def onboard_operations(session, limit: int) -> tuple[int, int]:
    # Operations model uses PurchaseRequest; map procurement POs onto Signals only
    # if the model shape differs, but load real supplier data as ops Signals.
    n_sig = 0
    for i, row in enumerate(loaders.load_procurement_compliance(limit=limit)):
        f = row["features"]
        compliant = row["ground_truth"]
        session.add(_signal(
            "operations", "ERP", f"po:{i}",
            f"{f.get('item_category')} — {f.get('order_status')}, qty {int(f.get('quantity',0))}, "
            f"unit ${f.get('unit_price')}, defects {int(f.get('defective_units',0))}, "
            f"compliant={compliant}",
            authority=0.9, pii=False))
        n_sig += 1
    await session.commit()
    return 0, n_sig


async def onboard_finance(session, limit: int) -> tuple[int, int]:
    """Real AR: 100 factoring customers and their invoices, with the actual
    invoice/due/settled dates and amounts — so aging, DSO, and late-payment
    figures the finance views compute are real history, not fabrication."""
    from datetime import datetime as _dt

    from app.finance.models.accounts_receivable import (
        Customer, CustomerInvoice, CustomerInvoiceStatus, CustomerStatus,
    )

    def _d(s: str):
        return _dt.strptime(s.strip(), "%m/%d/%Y").date()

    customers: dict[str, Customer] = {}
    settle_days: dict[str, list[int]] = {}
    n_inv = n_sig = 0
    for row in loaders.load_finance_late_payment(limit=limit):
        f = row["features"]
        cid = f["customer_id"]
        if cid not in customers:
            customers[cid] = Customer(
                id=_id(), tenant_id=TENANT,
                customer_code=f"RC-{cid}", name=f"RealCo Customer {cid}",
                status=CustomerStatus.ACTIVE,
                payment_terms_days=30, currency="USD",
            )
            session.add(customers[cid])
            settle_days[cid] = []
        settle_days[cid].append(f["days_to_settle"])

        late = row["ground_truth"]
        amount = round(f["invoice_amount"], 2)
        inv = CustomerInvoice(
            id=_id(), tenant_id=TENANT, customer_id=customers[cid].id,
            invoice_number=f"RC-{f['invoice_number']}",
            invoice_date=_d(f["invoice_date"]), due_date=_d(f["due_date"]),
            # Every invoice in this dataset was eventually settled.
            status=CustomerInvoiceStatus.PAID,
            subtotal=amount, total_amount=amount,
            amount_received=amount, balance_due=0,
            notes=(f"Settled {f['settled_date']} "
                   f"({f['days_late']} days late)" if late else
                   f"Settled {f['settled_date']} (on time)"),
        )
        session.add(inv)
        n_inv += 1
        session.add(_signal(
            "finance", "ERP", f"invoice:{inv.invoice_number}",
            f"${amount} due {f['due_date']} — settled {f['settled_date']}, "
            f"{'DISPUTED, ' if f['disputed'] else ''}"
            f"{str(f['days_late']) + ' days late' if late else 'on time'}",
            authority=0.95, pii=False))
        n_sig += 1

    # Real per-customer DSO from actual settlement history.
    for cid, cust in customers.items():
        days = settle_days[cid]
        cust.days_sales_outstanding = round(sum(days) / len(days), 1)

    await session.commit()
    return n_inv, n_sig


# CUAD category -> the risk level KAEOS's legal-review agent assigns the class.
_CLAUSE_RISK = {
    "HIGH": {"Uncapped Liability", "Non-Compete", "Exclusivity", "Ip Ownership Assignment",
             "Liquidated Damages", "Most Favored Nation", "Covenant Not To Sue",
             "Change Of Control", "Joint Ip Ownership", "Source Code Escrow"},
    "MEDIUM": {"Cap On Liability", "Audit Rights", "Minimum Commitment",
               "Revenue/Profit Sharing", "Termination For Convenience", "Anti-Assignment",
               "Rofr/Rofo/Rofn", "No-Solicit Of Employees", "No-Solicit Of Customers",
               "Volume Restriction", "Price Restrictions", "Post-Termination Services"},
}


async def onboard_legal(session, limit: int) -> tuple[int, int]:
    """Real contracts: CUAD v1's SEC-filed agreements with the clause spans the
    Atticus Project's lawyers extracted — clause_type and original_text are
    expert-labelled ground truth, not generated text."""
    import json as _json
    import re as _re
    from datetime import datetime as _dt

    from app.legal.models.contracts import (
        Contract, ContractClause, ContractStatus, ClauseRiskLevel,
    )

    def _risk(category: str) -> ClauseRiskLevel:
        if category in _CLAUSE_RISK["HIGH"]:
            return ClauseRiskLevel.HIGH
        if category in _CLAUSE_RISK["MEDIUM"]:
            return ClauseRiskLevel.MEDIUM
        return ClauseRiskLevel.LOW

    path = loaders._path(loaders.DATASET_MANIFEST["legal_clause_type"]["file"])
    with open(path, encoding="utf-8") as fh:
        contracts = _json.load(fh)["data"]

    n_con = n_sig = 0
    for contract in contracts[:limit]:
        title = contract["title"]
        # "LIMEENERGYCO_09_09_1999-EX-10-DISTRIBUTOR AGREEMENT" ->
        # counterparty LIMEENERGYCO, date 09/09/1999, type DISTRIBUTOR AGREEMENT.
        counterparty = title.split("_", 1)[0][:256] or "Unknown"
        tail = title.rsplit("-", 1)[-1].strip()
        contract_type = (tail if tail and not tail[0].isdigit() else "AGREEMENT")[:64]
        eff = None
        m = _re.search(r"_(\d{2})_(\d{2})_(\d{4})", title)
        if m:
            try:
                eff = _dt.strptime("/".join(m.groups()), "%m/%d/%Y").date()
            except ValueError:
                eff = None

        con = Contract(
            id=_id(), tenant_id=TENANT,
            title=title[:256], counterparty=counterparty,
            contract_type=contract_type,
            # SEC-filed exhibits are executed agreements.
            status=ContractStatus.SIGNED,
            effective_date=eff,
        )
        session.add(con)
        n_con += 1

        high = 0
        n_clauses = 0
        for qa in contract["paragraphs"][0]["qas"]:
            category = qa["id"].split("__")[-1].strip()
            if category in loaders.CUAD_METADATA_CATEGORIES:
                continue
            for ans in qa["answers"]:
                text = (ans.get("text") or "").strip()
                if not text:
                    continue
                risk = _risk(category)
                if risk == ClauseRiskLevel.HIGH:
                    high += 1
                session.add(ContractClause(
                    id=_id(), tenant_id=TENANT, contract_id=con.id,
                    clause_type=category[:64], original_text=text,
                    risk_level=risk,
                ))
                n_clauses += 1

        session.add(_signal(
            "legal", "CLM", f"contract:{counterparty}",
            f"{contract_type} — {n_clauses} expert-labelled clauses, "
            f"{high} high-risk",
            authority=0.95, pii=False))
        n_sig += 1
        # Contracts carry thousands of clause rows in aggregate; flush per
        # contract keeps memory flat without committing half an onboard.
        await session.flush()

    await session.commit()
    return n_con, n_sig


async def onboard(limit: int = 500):
    present = loaders.available()
    missing = [k for k, v in present.items() if not v]
    if missing:
        logger.warning(f"Missing raw datasets (will skip): {missing}. "
                       f"Download via scripts described in benchmark manifest.")

    await init_db()
    async with AsyncSessionLocal() as session:
        logger.info(f"Onboarding '{COMPANY}' as {TENANT} (limit {limit}/domain)...")
        await _clear(session)

        summary = {}
        if present.get("hr_attrition"):
            summary["hr"] = await onboard_hr(session, limit)
        if present.get("support_priority"):
            summary["support"] = await onboard_support(session, limit)
        if present.get("incident_priority"):
            summary["engineering"] = await onboard_engineering(session, limit)
        if present.get("sales_conversion"):
            summary["sales"] = await onboard_sales(session, limit)
        if present.get("procurement_compliance"):
            summary["operations"] = await onboard_operations(session, limit)
        if present.get("finance_late_payment"):
            summary["finance"] = await onboard_finance(session, limit)
        if present.get("legal_clause_type"):
            summary["legal"] = await onboard_legal(session, limit)

        logger.info("=" * 60)
        logger.info(f"ONBOARDED {COMPANY} ({TENANT}):")
        total_records = total_signals = 0
        for dom, (recs, sigs) in summary.items():
            logger.info(f"  {dom:12} {recs:>5} records, {sigs:>5} signals")
            total_records += recs
            total_signals += sigs
        logger.info(f"  {'TOTAL':12} {total_records:>5} records, {total_signals:>5} signals")
        logger.info("=" * 60)
        logger.info(f"View with: X-Tenant-ID: {TENANT}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=500)
    args = ap.parse_args()
    asyncio.run(onboard(limit=args.limit))
