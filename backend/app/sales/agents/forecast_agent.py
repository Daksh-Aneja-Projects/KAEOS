"""KAEOS Sales Domain - Forecast Agent

Context-grounding: the agent loads the real entity and reasons over its
content. Passing only an opaque id left the model classifying an identifier
(confirmed ungrounded on real onboarded data), so facts are non-optional.
"""
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.sales.agents.gated_runner import run_gated_sales_skill
from app.sales.models.forecasting import ForecastLine, SalesForecast
from app.services.json_utils import plain_facts


class ForecastAgent:
    async def predict_forecast(self, db: AsyncSession, forecast_id: str, tenant_id: str) -> Dict[str, Any]:
        # The forecasts list serves one row per REP LINE (ForecastLine id)
        # plus aggregate rows (SalesForecast id) - accept either.
        line = None
        fc = (await db.execute(
            select(SalesForecast).where(
                SalesForecast.id == forecast_id, SalesForecast.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if not fc:
            line = (await db.execute(
                select(ForecastLine).where(
                    ForecastLine.id == forecast_id, ForecastLine.tenant_id == tenant_id)
            )).scalar_one_or_none()
            if line:
                fc = (await db.execute(
                    select(SalesForecast).where(
                        SalesForecast.id == line.forecast_id, SalesForecast.tenant_id == tenant_id)
                )).scalar_one_or_none()
        if not fc:
            raise ValueError(f"Forecast {forecast_id} not found")

        facts = {
            "quarter": fc.quarter,
            "target_quota": fc.target_quota,
            "commit_amount": fc.commit_amount,
            "best_case_amount": fc.best_case_amount,
            "pipeline_amount": fc.pipeline_amount,
            "prior_ai_prediction": fc.ai_predicted_amount,
        }
        if line:
            facts["rep_line"] = {
                "commit_amount": line.commit_amount,
                "best_case_amount": line.best_case_amount,
                "pipeline_amount": line.pipeline_amount,
            }
        facts = plain_facts(facts)
        return await run_gated_sales_skill(
            skill_id="sales_forecast",
            steps=[{"step": 1, "name": "Forecast",
                    "prompt": f"Predict the quarter outcome from these pipeline numbers: {facts}"}],
            context={
                "forecast_id": forecast_id, "tenant_id": tenant_id, **facts,
                "instruction": "Output strict JSON: {predicted_amount, quota_attainment_pct, confidence, risks}.",
            },
            tenant_id=tenant_id,
        )
