"""
KAEOS Finance Domain — Reporting Agent

Auto-generate P&L, Balance Sheet, Cash Flow statements with AI commentary.
"""
import logging
from typing import Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.services.llm_router import LLMRouter
from app.finance.models.core import ChartOfAccount, AccountType

logger = logging.getLogger(__name__)


class ReportingAgent:
    def __init__(self):
        self.router = LLMRouter()
        self.persona = "You are the KAEOS Financial Reporting Agent. Expert in generating GAAP-compliant financial statements with executive-level commentary."

    async def generate_income_statement(self, db: AsyncSession, tenant_id: str, fiscal_year: int) -> Dict[str, Any]:
        # Revenue accounts
        rev_q = await db.execute(
            select(ChartOfAccount).where(ChartOfAccount.tenant_id == tenant_id).where(ChartOfAccount.account_type == AccountType.REVENUE)
        )
        rev_accounts = rev_q.scalars().all()
        total_revenue = sum(float(a.current_balance or 0) for a in rev_accounts)

        # Expense accounts
        exp_q = await db.execute(
            select(ChartOfAccount).where(ChartOfAccount.tenant_id == tenant_id).where(ChartOfAccount.account_type == AccountType.EXPENSE)
        )
        exp_accounts = exp_q.scalars().all()
        total_expenses = sum(float(a.current_balance or 0) for a in exp_accounts)

        net_income = total_revenue - total_expenses

        report_data = {
            "revenue": {"total": total_revenue, "accounts": [{"code": a.account_code, "name": a.account_name, "balance": float(a.current_balance or 0)} for a in rev_accounts]},
            "expenses": {"total": total_expenses, "accounts": [{"code": a.account_code, "name": a.account_name, "balance": float(a.current_balance or 0)} for a in exp_accounts]},
            "net_income": net_income,
            "margin_pct": round(net_income / max(total_revenue, 1) * 100, 1)
        }

        return report_data

    async def generate_balance_sheet(self, db: AsyncSession, tenant_id: str) -> Dict[str, Any]:
        assets_q = await db.execute(select(ChartOfAccount).where(ChartOfAccount.tenant_id == tenant_id).where(ChartOfAccount.account_type == AccountType.ASSET))
        liab_q = await db.execute(select(ChartOfAccount).where(ChartOfAccount.tenant_id == tenant_id).where(ChartOfAccount.account_type == AccountType.LIABILITY))
        equity_q = await db.execute(select(ChartOfAccount).where(ChartOfAccount.tenant_id == tenant_id).where(ChartOfAccount.account_type == AccountType.EQUITY))

        assets = assets_q.scalars().all()
        liabilities = liab_q.scalars().all()
        equity = equity_q.scalars().all()

        total_assets = sum(float(a.current_balance or 0) for a in assets)
        total_liabilities = sum(float(a.current_balance or 0) for a in liabilities)
        total_equity = sum(float(a.current_balance or 0) for a in equity)

        return {
            "assets": {"total": total_assets, "accounts": [{"code": a.account_code, "name": a.account_name, "balance": float(a.current_balance or 0)} for a in assets]},
            "liabilities": {"total": total_liabilities, "accounts": [{"code": a.account_code, "name": a.account_name, "balance": float(a.current_balance or 0)} for a in liabilities]},
            "equity": {"total": total_equity, "accounts": [{"code": a.account_code, "name": a.account_name, "balance": float(a.current_balance or 0)} for a in equity]},
            "balanced": abs(total_assets - (total_liabilities + total_equity)) < 0.01
        }
