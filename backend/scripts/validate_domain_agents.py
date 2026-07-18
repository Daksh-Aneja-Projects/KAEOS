"""
Validate every context-grounded domain agent against REAL rows.

For each rewritten agent this script picks a real entity (preferring the
Kaggle-onboarded tenant_realco, falling back to tenant_acme seeds), runs the
agent through its full gated pipeline, and records:
  - status returned (SUCCESS_CLEAN / PENDING_HITL / error)
  - whether the entity's actual content made it into the skill context
    (grounding check: a known content fragment must appear in the stored
    execution context)

Run:  python scripts/validate_domain_agents.py
Writes: benchmark/agent_validation_report.json
"""
import asyncio
import json
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.core.database import AsyncSessionLocal as async_session  # noqa: E402

REALCO = "tenant_realco"
ACME = "tenant_acme"

REPORT = Path(__file__).resolve().parents[1] / "benchmark" / "agent_validation_report.json"


async def _pick(db, model, tenant_col=True):
    """First row preferring tenant_realco, then tenant_acme, then any."""
    if tenant_col:
        for t in (REALCO, ACME):
            row = (await db.execute(
                select(model).where(model.tenant_id == t).limit(1)
            )).scalars().first()
            if row:
                return row, t
    row = (await db.execute(select(model).limit(1))).scalars().first()
    return row, getattr(row, "tenant_id", None) if row else (None, None)


def _spec():
    """(name, agent factory, method, entity model, content probe fields)"""
    from app.finance.agents.ar_agent import ARAgent
    from app.finance.agents.budget_agent import BudgetAgent
    from app.finance.agents.expense_agent import ExpenseAgent
    from app.finance.agents.tax_agent import TaxAgent
    from app.finance.models.accounts_receivable import CustomerInvoice
    from app.finance.models.budgeting import Budget
    from app.finance.models.expense import ExpenseReport
    from app.hr.models.payroll import PayrollRun
    from app.legal.agents.compliance_audit_agent import ComplianceAuditAgent
    from app.legal.agents.contract_review_agent import ContractReviewAgent
    from app.legal.agents.litigation_agent import LitigationAgent
    from app.legal.agents.privacy_dsar_agent import PrivacyDSARAgent
    from app.legal.models.compliance import ComplianceObligation
    from app.legal.models.contracts import Contract
    from app.legal.models.litigation import Case
    from app.legal.models.privacy import DataSubjectRequest
    from app.operations.agents.procurement_agent import ProcurementAgent
    from app.operations.agents.project_agent import ProjectAgent
    from app.operations.agents.qa_agent import QAAgent
    from app.operations.agents.vendor_agent import VendorAgent
    from app.operations.models.procurement import PurchaseRequest
    from app.operations.models.projects import Project
    from app.operations.models.quality import Inspection
    from app.operations.models.vendors import VendorContract
    from app.sales.agents.account_health_agent import AccountHealthAgent
    from app.sales.agents.churn_agent import ChurnAgent
    from app.sales.agents.forecast_agent import ForecastAgent
    from app.sales.agents.lead_scoring_agent import LeadScoringAgent
    from app.sales.agents.pipeline_coach_agent import PipelineCoachAgent
    from app.sales.agents.proposal_gen_agent import ProposalGenAgent
    from app.sales.models.accounts import Account
    from app.sales.models.forecasting import SalesForecast
    from app.sales.models.leads import Lead
    from app.sales.models.pipeline import Opportunity
    from app.support.agents.auto_resolve_agent import AutoResolveAgent
    from app.support.agents.csat_agent import CSATAgent
    from app.support.agents.escalation_agent import EscalationAgent
    from app.support.agents.triage_agent import TriageAgent
    from app.support.models.feedback import NPS_Survey
    from app.support.models.tickets import Ticket

    return [
        ("finance.ar_dunning",       ARAgent(),              "generate_dunning",   CustomerInvoice, ["invoice_number"]),
        ("finance.budget_variance",  BudgetAgent(),          "analyze_variance",   Budget,          ["name"]),
        ("finance.expense_audit",    ExpenseAgent(),         "audit_report",       ExpenseReport,   ["title"]),
        ("finance.payroll_audit",    TaxAgent(),             "audit_payroll",      PayrollRun,      ["total_gross"]),
        ("legal.compliance_audit",   ComplianceAuditAgent(), "audit_obligation",   ComplianceObligation, ["title"]),
        ("legal.contract_review",    ContractReviewAgent(),  "review_contract",    Contract,        ["title", "counterparty"]),
        ("legal.litigation_eval",    LitigationAgent(),      "evaluate_case",      Case,            ["case_name"]),
        ("legal.privacy_dsar",       PrivacyDSARAgent(),     "process_dsar",       DataSubjectRequest, ["request_type"]),
        ("ops.procurement_audit",    ProcurementAgent(),     "audit_request",      PurchaseRequest, ["item_description"]),
        ("ops.project_eval",         ProjectAgent(),         "evaluate_project",   Project,         ["name"]),
        ("ops.qa_inspect",           QAAgent(),              "inspect_qa",         Inspection,      ["inspected_item"]),
        ("ops.vendor_risk",          VendorAgent(),          "evaluate_vendor",    VendorContract,  ["vendor_name"]),
        ("sales.account_health",     AccountHealthAgent(),   "assess_health",      Account,         ["name"]),
        ("sales.churn_prevention",   ChurnAgent(),           "identify_churn_risk", Account,        ["name"]),
        ("sales.forecast",           ForecastAgent(),        "predict_forecast",   SalesForecast,   ["quarter"]),
        ("sales.lead_scoring",       LeadScoringAgent(),     "score_lead",         Lead,            ["company"]),
        ("sales.pipeline_coach",     PipelineCoachAgent(),   "coach_opportunity",  Opportunity,     ["name"]),
        ("sales.proposal_gen",       ProposalGenAgent(),     "generate_proposal",  Opportunity,     ["name"]),
        ("support.triage",           TriageAgent(),          "triage_ticket",      Ticket,          ["subject"]),
        ("support.auto_resolve",     AutoResolveAgent(),     "generate_response",  Ticket,          ["subject"]),
        ("support.escalation",       EscalationAgent(),      "escalate_ticket",    Ticket,          ["subject"]),
        ("support.csat_analysis",    CSATAgent(),            "analyze_surveys",    NPS_Survey,      ["score"]),
    ]


async def _grounding_ok(db, execution_id, probes):
    """Confirm the entity's actual content is inside the stored execution context."""
    if not execution_id or not probes:
        return None
    from app.models.domain import SkillExecution
    ex = (await db.execute(
        select(SkillExecution).where(SkillExecution.id == execution_id)
    )).scalar_one_or_none()
    if not ex:
        return None
    blob = json.dumps(ex.context or {}, default=str)
    return all(str(p) in blob for p in probes if p not in (None, ""))


async def main():
    results = []
    specs = _spec()
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None
    if only:
        specs = [s for s in specs if s[0].startswith(only)]

    for name, agent, method, model, probe_fields in specs:
        try:
            async with async_session() as db:
                row, tenant = await _pick(db, model)
        except Exception as e:
            # e.g. enum-invalid rows: the read itself can raise
            results.append({"agent": name, "status": f"ENTITY_READ_ERROR: {e}", "tenant": None})
            print(f"[FAIL] {name}: entity read failed: {e}")
            continue
        if not row:
            results.append({"agent": name, "status": "NO_DATA", "tenant": None})
            print(f"[skip] {name}: no rows for entity {model.__name__}")
            continue
        if not tenant:
            # Was `tenant` at the call sites below. Agents now
            # REQUIRE a real tenant, and silently substituting "default" would
            # validate an agent against the wrong tenant's data - the exact
            # footgun that let the agents ship without tenant filters at all.
            results.append({"agent": name, "status": "NO_TENANT", "tenant": None})
            print(f"[FAIL] {name}: entity {model.__name__} row has no tenant_id")
            continue

        probes = [getattr(getattr(row, f, None), "value", getattr(row, f, None)) for f in probe_fields]
        t0 = time.time()
        is_finance = name.startswith("finance.")
        try:
            if is_finance:
                # SOX control: a direct (unapproved) call MUST block at the
                # compliance gate. Prove that first, then run the approved path.
                async with async_session() as db:
                    blocked = await getattr(agent, method)(db, row.id, tenant)
                sox_blocked = blocked.get("status") == "BLOCKED_COMPLIANCE"
                async with async_session() as db:
                    out = await getattr(agent, method)(
                        db, row.id, tenant, has_human_approver=True
                    )
            else:
                sox_blocked = None
                async with async_session() as db:
                    out = await getattr(agent, method)(db, row.id, tenant)
            status = out.get("status", "?") if isinstance(out, dict) else str(type(out))
            exec_id = out.get("execution_id") if isinstance(out, dict) else None
            async with async_session() as db:
                grounded = await _grounding_ok(db, exec_id, probes)
            rec = {
                "agent": name, "tenant": tenant, "entity_id": row.id,
                "status": status, "grounded": grounded,
                "seconds": round(time.time() - t0, 1),
            }
            if sox_blocked is not None:
                rec["sox_blocks_unapproved_call"] = sox_blocked
            results.append(rec)
            extra = "" if sox_blocked is None else f" sox_block={sox_blocked}"
            print(f"[ok]   {name}: status={status} grounded={grounded}{extra} ({round(time.time()-t0,1)}s)")
        except Exception as e:
            results.append({
                "agent": name, "tenant": tenant, "entity_id": row.id,
                "status": f"ERROR: {e}", "grounded": False,
                "seconds": round(time.time() - t0, 1),
            })
            print(f"[FAIL] {name}: {e}")
            traceback.print_exc()

    # SLA agent has no entity id (tenant-wide)
    from app.support.agents.sla_agent import SLAAgent
    t0 = time.time()
    try:
        async with async_session() as db:
            out = await SLAAgent().check_sla(db, ACME)
        results.append({"agent": "support.sla_monitor", "tenant": ACME,
                        "status": out.get("status", "?"),
                        "seconds": round(time.time() - t0, 1)})
        print(f"[ok]   support.sla_monitor: status={out.get('status','?')}")
    except Exception as e:
        results.append({"agent": "support.sla_monitor", "tenant": ACME,
                        "status": f"ERROR: {e}", "seconds": round(time.time() - t0, 1)})
        print(f"[FAIL] support.sla_monitor: {e}")

    ok = sum(1 for r in results if not str(r["status"]).startswith("ERROR") and r["status"] != "NO_DATA")
    grounded = sum(1 for r in results if r.get("grounded"))
    summary = {
        "total_agents": len(results),
        "succeeded": ok,
        "grounding_confirmed": grounded,
        "results": results,
    }
    REPORT.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(f"\n== {ok}/{len(results)} agents succeeded, {grounded} grounding-confirmed ==")
    print(f"report: {REPORT}")


if __name__ == "__main__":
    asyncio.run(main())
