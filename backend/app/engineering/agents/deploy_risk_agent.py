"""KAEOS Engineering Domain — Deploy Risk Agent"""
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engineering.agents.gated_runner import extract_decision, run_gated_engineering_skill
from app.engineering.models.core import Service
from app.engineering.models.delivery import Deployment, PullRequest, RiskLevel
from app.engineering.models.ops import PipelineRun, PipelineStatus
from app.services.json_utils import plain_facts

logger = logging.getLogger(__name__)

# A pipeline run history that failed this often (or worse) over the recent
# window is a real risk signal, not noise from one flaky run.
_PIPELINE_FAILURE_RATE_THRESHOLD_PCT = 30.0


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

        # Real CI build/test history for the service, not just the single PR's
        # ci_passing flag at the moment it was last reviewed — a service whose
        # last 10 pipeline runs are mostly red is riskier to ship to, regardless
        # of what any one PR says.
        recent_runs: List[PipelineRun] = []
        if deploy.service_id:
            recent_runs = (await db.execute(
                select(PipelineRun)
                .where(
                    PipelineRun.service_id == deploy.service_id,
                    PipelineRun.tenant_id == tenant_id,
                    PipelineRun.status.in_([PipelineStatus.SUCCEEDED, PipelineStatus.FAILED]),
                )
                .order_by(PipelineRun.started_at.desc())
                .limit(10)
            )).scalars().all()
        pipeline_failure_rate = self._pipeline_failure_rate(recent_runs)

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
            # None (not 0) when there is no pipeline history to derive from -
            # the honesty contract forbids presenting "no data" as "0% failure".
            "recent_pipeline_failure_rate_pct": pipeline_failure_rate,
            "recent_pipeline_runs_considered": len(recent_runs),
        }
        facts = plain_facts(facts)

        steps = [
            {"step": 1, "name": "Load Deploy Context", "prompt": f"Deployment facts: {facts}"},
            {"step": 2, "name": "Score Risk",
             "prompt": (
                 "Score the risk of shipping this deployment to production. Weigh: service tier, "
                 "current service health, remaining error budget, open incidents, recent CI "
                 "pipeline failure history, and the risk of the underlying change. Respond as "
                 'JSON with keys "risk_level" (LOW|MEDIUM|HIGH|CRITICAL), "risk_score" (0-100), '
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
    def _pipeline_failure_rate(runs: List[PipelineRun]) -> Optional[float]:
        """Failure rate over the recent (SUCCEEDED|FAILED) pipeline runs, or
        None when there is no history to derive one from — never a fabricated
        0%."""
        if not runs:
            return None
        failed = sum(1 for r in runs if r.status == PipelineStatus.FAILED)
        return round(failed / len(runs) * 100, 1)

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
        pipe_fail = facts.get("recent_pipeline_failure_rate_pct")
        if pipe_fail is not None and pipe_fail >= _PIPELINE_FAILURE_RATE_THRESHOLD_PCT:
            score += 15
        return round(min(100.0, score), 1)

    @staticmethod
    def _resolve_level(model_answer: Any, score: float) -> RiskLevel:
        if isinstance(model_answer, str):
            try:
                return RiskLevel(model_answer.strip().upper())
            except ValueError:
                # An invalid model label is DISCARDED, not trusted: control falls
                # through to the deterministic score thresholds below.
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
        pipe_fail = facts.get("recent_pipeline_failure_rate_pct")
        if pipe_fail is not None and pipe_fail >= _PIPELINE_FAILURE_RATE_THRESHOLD_PCT:
            reasons.append(f"{pipe_fail:.0f}% of recent CI pipeline runs failed")
        detail = ", ".join(reasons) if reasons else "no elevated risk factors"
        return f"Risk scored {score}/100 ({detail})."
