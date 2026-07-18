"""KAEOS Finance Domain - Expense Audit Agent

Context-grounding: the agent loads the real entity and reasons over its
content. Passing only an opaque id left the model classifying an identifier
(confirmed ungrounded on real onboarded data), so facts are non-optional.
"""
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.finance.agents.gated_runner import run_gated_finance_skill
from app.finance.models.expense import ExpenseReport
from app.services.json_utils import plain_facts


def _v(x):
    return getattr(x, "value", x)


class ExpenseAgent:
    # tenant_id is required with no default: a default silently falls back to
    # another tenant's data.
    async def audit_report(self, db: AsyncSession, report_id: str, tenant_id: str, has_human_approver: bool = False) -> Dict[str, Any]:
        report = (await db.execute(
            select(ExpenseReport).where(ExpenseReport.id == report_id, ExpenseReport.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if not report:
            raise ValueError(f"Expense report {report_id} not found")

        facts = {
            "report_number": report.report_number,
            "title": report.title,
            "description": (report.description or "")[:1000],
            "status": _v(report.status),
            "total_amount": report.total_amount,
            "currency": report.currency,
            "department": report.department,
            "period_start": str(report.expense_period_start) if report.expense_period_start else None,
            "period_end": str(report.expense_period_end) if report.expense_period_end else None,
            "prior_policy_violations": report.ai_policy_violations,
        }
        facts = plain_facts(facts)
        return await run_gated_finance_skill(
            skill_id="finance_expense_audit",
            steps=[{"step": 1, "name": "Audit",
                    "prompt": f"Audit this expense report for policy violations and anomalies: {facts}"}],
            context={
                "report_id": report_id, "tenant_id": tenant_id, "has_human_approver": has_human_approver, **facts,
                "instruction": "Output strict JSON: {policy_violations, anomaly_flags, approve_or_review}.",
            },
            tenant_id=tenant_id,
        )
