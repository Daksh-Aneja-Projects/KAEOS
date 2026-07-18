"""KAEOS Finance Domain - Payroll Tax Audit Agent

Context-grounding: the agent loads the real entity and reasons over its
content. Passing only an opaque id left the model classifying an identifier
(confirmed ungrounded on real onboarded data), so facts are non-optional.
"""
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.finance.agents.gated_runner import run_gated_finance_skill
from app.hr.models.payroll import PayrollRun
from app.services.json_utils import plain_facts


def _v(x):
    return getattr(x, "value", x)


class TaxAgent:
    # tenant_id is required with no default: a default silently falls back to
    # another tenant's data.
    async def audit_payroll(self, db: AsyncSession, payroll_id: str, tenant_id: str, has_human_approver: bool = False) -> Dict[str, Any]:
        run = (await db.execute(
            select(PayrollRun).where(PayrollRun.id == payroll_id, PayrollRun.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if not run:
            raise ValueError(f"Payroll run {payroll_id} not found")

        facts = {
            "period_start": str(run.period_start) if run.period_start else None,
            "period_end": str(run.period_end) if run.period_end else None,
            "pay_date": str(run.pay_date) if run.pay_date else None,
            "status": _v(run.status),
            "total_gross": run.total_gross,
            "total_net": run.total_net,
            "total_taxes": run.total_taxes,
            "total_deductions": run.total_deductions,
            "prior_anomalies": run.ai_anomalies_detected,
        }
        facts = plain_facts(facts)
        return await run_gated_finance_skill(
            skill_id="finance_payroll_audit",
            steps=[{"step": 1, "name": "Audit",
                    "prompt": f"Audit this payroll run for tax-withholding anomalies: {facts}"}],
            context={
                "payroll_id": payroll_id, "tenant_id": tenant_id, "has_human_approver": has_human_approver, **facts,
                "instruction": "Output strict JSON: {anomalies, withholding_ok, requires_review}.",
            },
            tenant_id=tenant_id,
        )
