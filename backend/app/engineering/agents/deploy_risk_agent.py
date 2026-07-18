"""KAEOS Engineering Domain — Deploy Risk Agent"""
import logging
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engineering.agents.gated_runner import extract_decision, run_gated_engineering_skill
from app.engineering.models.core import Service
from app.engineering.models.delivery import Deployment, PullRequest, RiskLevel
from app.services.json_utils import plain_facts

logger = logging.getLogger(__name__)


class DeployRiskAgent:
    """
    Scores the risk of a production deployment.

    This skill is in ALWAYS_HITL_SKILLS: it never self-approves a production
    change. It produces the evidence a human approves against.
    """

    async def assess_deployment(
        self, db: AsyncSession, deployment_id: str, tenant_id: str
    ) -> Dict[str, Any]:
        deploy = (await db.execute(
            select(Deployment).where(
                Deployment.id == deployment_id, Deployment.tenant_id == tenant_id
            )
        )).scalar_one_or_none()
        if not deploy:
            raise ValueError("Deployment not found")

        service = None
        if deploy.service_id:
            service = (await db.execute(
                select(Service).where(
                    Service.id == deploy.service_id, Service.tenant_id == tenant_id
                )
            )).scalar_one_or_none()

        pr = None
        if deploy.pull_request_id:
            pr = (await db.execute(
                select(PullRequest).where(
                    PullRequest.id == deploy.pull_request_id,
                    PullRequest.tenant_id == tenant_id,
                )
            )).scalar_one_or_none()

        facts = {
            "version": deploy.version,
            "environment": deploy.environment,
            "change_count": deploy.change_count,
            "service": service.name if service else None,
            "service_tier": service.tier.value if service and service.tier else None,
            "service_health": service.health.value if service and service.health else None,
            "error_budget_remaining_pct": service.error_budget_remaining_pct if service else None,
            "open_incidents": service.open_incidents if service else 0,
            "pr_risk": pr.ai_risk_level.value if pr and pr.ai_risk_level else None,
            "pr_ci_passing": pr.ci_passing if pr else None,
        }
        facts = plain_facts(facts)

        steps = [
            {"step": 1, "name": "Load Deploy Context", "prompt": f"Deployment facts: {facts}"},
            {"step": 2, "name": "Score Risk",
             "prompt": (
                 "Score the risk of shipping this deployment to production. Weigh: service tier, "
                 "current service health, remaining error budget, open incidents, and the risk of "
                 "the underlying change. Respond as JSON with keys "
                 '"risk_level" (LOW|MEDIUM|HIGH|CRITICAL), "risk_score" (0-100), '
                 'and "rationale" (one sentence).'
             )},
        ]

        result = await run_gated_engineering_skill(
            skill_id="engineering_deploy_approval",   # always-HITL
            steps=steps,
            context={"deployment_id": deployment_id, "tenant_id": tenant_id, "facts": facts},
            tenant_id=tenant_id,
        )

        decision = extract_decision(result)
        score = self._resolve_score(decision.get("risk_score"), facts)
        risk = self._resolve_level(decision.get("risk_level"), score)

        deploy.ai_risk_level = risk
        deploy.ai_risk_score = score
        deploy.ai_rationale = decision.get("rationale") or self._fallback_rationale(facts, score)
        await db.commit()

        return {
            **result,
            "version": deploy.version,
            "risk_level": risk.value,
            "risk_score": score,
            "rationale": deploy.ai_rationale,
            "requires_human_approval": True,
        }

    @staticmethod
    def _resolve_score(model_answer: Any, facts: Dict[str, Any]) -> float:
        """Deterministic risk score; the model may only refine within bounds."""
        if isinstance(model_answer, (int, float)) and 0 <= float(model_answer) <= 100:
            return round(float(model_answer), 1)

        score = 20.0
        if facts.get("service_tier") == "TIER_1":
            score += 25
        if facts.get("service_health") in ("DEGRADED", "OUTAGE"):
            score += 25
        budget = facts.get("error_budget_remaining_pct")
        if budget is not None and budget < 25:
            score += 15
        score += min(20, (facts.get("open_incidents") or 0) * 10)
        if facts.get("pr_risk") in ("HIGH", "CRITICAL"):
            score += 15
        if facts.get("pr_ci_passing") is False:
            score += 20
        return round(min(100.0, score), 1)

    @staticmethod
    def _resolve_level(model_answer: Any, score: float) -> RiskLevel:
        if isinstance(model_answer, str):
            try:
                return RiskLevel(model_answer.strip().upper())
            except ValueError:
                pass
        if score >= 75:
            return RiskLevel.CRITICAL
        if score >= 50:
            return RiskLevel.HIGH
        if score >= 30:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW

    @staticmethod
    def _fallback_rationale(facts: Dict[str, Any], score: float) -> str:
        reasons = []
        if facts.get("service_tier") == "TIER_1":
            reasons.append("tier-1 service")
        if facts.get("service_health") in ("DEGRADED", "OUTAGE"):
            reasons.append(f"service currently {facts['service_health'].lower()}")
        if (facts.get("open_incidents") or 0) > 0:
            reasons.append(f"{facts['open_incidents']} open incident(s)")
        budget = facts.get("error_budget_remaining_pct")
        if budget is not None and budget < 25:
            reasons.append(f"only {budget:.0f}% error budget left")
        detail = ", ".join(reasons) if reasons else "no elevated risk factors"
        return f"Risk scored {score}/100 ({detail})."
