"""KAEOS Engineering Domain — Incident Triage Agent (IT Ops)"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engineering.agents.gated_runner import extract_decision, run_gated_engineering_skill
from app.engineering.models.core import Service
from app.engineering.models.delivery import Deployment, DeployStatus
from app.engineering.models.incidents import Incident, IncidentSeverity
from app.services.json_utils import plain_facts

logger = logging.getLogger(__name__)


class IncidentAgent:
    """Triages an incident: severity, probable cause, recommended action."""

    async def triage_incident(
        self, db: AsyncSession, incident_id: str, tenant_id: str
    ) -> Dict[str, Any]:
        incident = (await db.execute(
            select(Incident).where(
                Incident.id == incident_id, Incident.tenant_id == tenant_id
            )
        )).scalar_one_or_none()
        if not incident:
            raise ValueError("Incident not found")

        service = None
        if incident.service_id:
            service = (await db.execute(
                select(Service).where(
                    Service.id == incident.service_id, Service.tenant_id == tenant_id
                )
            )).scalar_one_or_none()

        # Correlate against the most recent deploy that could actually have
        # caused this incident: it must have SHIPPED (a pending or failed-to-start
        # deploy changed nothing) and must precede detection. Without both filters
        # the agent will happily blame a deploy that never reached production.
        recent_deploy = None
        if incident.service_id:
            causal_states = (DeployStatus.SUCCEEDED, DeployStatus.ROLLED_BACK, DeployStatus.FAILED)
            q = (
                select(Deployment)
                .where(
                    Deployment.service_id == incident.service_id,
                    Deployment.tenant_id == tenant_id,
                    Deployment.status.in_(causal_states),
                )
                .order_by(Deployment.started_at.desc())
                .limit(1)
            )
            if incident.detected_at:
                q = q.where(Deployment.started_at <= incident.detected_at)
            recent_deploy = (await db.execute(q)).scalar_one_or_none()

        facts = {
            "title": incident.title,
            "description": incident.description,
            "recorded_severity": incident.severity.value if incident.severity else None,
            "customer_impacting": incident.customer_impacting,
            "affected_users": incident.affected_users,
            "service": service.name if service else None,
            "service_tier": service.tier.value if service and service.tier else None,
            "error_budget_remaining_pct": service.error_budget_remaining_pct if service else None,
            "recent_deploy": (
                {"version": recent_deploy.version, "status": recent_deploy.status.value}
                if recent_deploy else None
            ),
        }
        facts = plain_facts(facts)

        steps = [
            {"step": 1, "name": "Load Incident Context", "prompt": f"Incident facts: {facts}"},
            {"step": 2, "name": "Correlate Recent Changes",
             "prompt": "Correlate this incident against the most recent deployment to the affected service."},
            {"step": 3, "name": "Triage",
             "prompt": (
                 "Assign a severity and propose the immediate action. Respond as JSON with keys "
                 '"severity" (SEV1|SEV2|SEV3|SEV4), "probable_cause" (one sentence), '
                 'and "recommended_action" (one sentence).'
             )},
        ]

        result = await run_gated_engineering_skill(
            skill_id="engineering_incident_triage",
            steps=steps,
            context={"incident_id": incident_id, "tenant_id": tenant_id, "facts": facts},
            tenant_id=tenant_id,
        )

        decision = extract_decision(result)
        severity = self._resolve_severity(decision.get("severity"), facts)

        incident.ai_severity_assessment = severity.value
        incident.ai_probable_cause = decision.get("probable_cause") or self._fallback_cause(facts)
        incident.ai_recommended_action = (
            decision.get("recommended_action") or self._fallback_action(severity, facts)
        )
        incident.ai_triaged_at = datetime.now(timezone.utc)
        if recent_deploy:
            incident.suspected_deployment_id = recent_deploy.id
        await db.commit()

        return {
            **result,
            "incident_number": incident.incident_number,
            "severity": severity.value,
            "probable_cause": incident.ai_probable_cause,
            "recommended_action": incident.ai_recommended_action,
            "correlated_deployment": recent_deploy.version if recent_deploy else None,
        }

    # Severity ordering — lower number is more severe.
    _SEV_RANK = {IncidentSeverity.SEV1: 1, IncidentSeverity.SEV2: 2,
                 IncidentSeverity.SEV3: 3, IncidentSeverity.SEV4: 4}

    @classmethod
    def _resolve_severity(cls, model_answer: Any, facts: Dict[str, Any]) -> IncidentSeverity:
        """
        Assess severity, but NEVER silently de-escalate below what was recorded.

        Triage exists to catch under-classification, so it may raise severity on
        strong signals (customer impact, large user counts, tier-1 service,
        exhausted error budget). It must not LOWER a recorded SEV1 to SEV2 just
        because a field like affected_users is empty — a missing value is not
        evidence that an incident is less severe. That default-value hazard would
        quietly downgrade real production incidents.
        """
        # Independent assessment from impact signals.
        if facts.get("customer_impacting") and (facts.get("affected_users") or 0) > 1000:
            assessed = IncidentSeverity.SEV1
        elif facts.get("customer_impacting"):
            assessed = IncidentSeverity.SEV2
        else:
            assessed = IncidentSeverity.SEV3

        # Escalators: a tier-1 service or a spent error budget raises severity.
        if facts.get("service_tier") == "TIER_1" and cls._SEV_RANK[assessed] > 2:
            assessed = IncidentSeverity.SEV2
        budget = facts.get("error_budget_remaining_pct")
        if budget is not None and budget < 10 and cls._SEV_RANK[assessed] > 1:
            assessed = IncidentSeverity(f"SEV{cls._SEV_RANK[assessed] - 1}")

        # A valid model label may only ESCALATE, never de-escalate.
        if isinstance(model_answer, str):
            try:
                model_sev = IncidentSeverity(model_answer.strip().upper())
                if cls._SEV_RANK[model_sev] < cls._SEV_RANK[assessed]:
                    assessed = model_sev
            except ValueError:
                pass

        # Floor: never return less severe than what was already recorded.
        recorded = facts.get("recorded_severity")
        if recorded:
            try:
                rec_sev = IncidentSeverity(recorded)
                if cls._SEV_RANK[rec_sev] < cls._SEV_RANK[assessed]:
                    assessed = rec_sev
            except ValueError:
                pass

        return assessed

    @staticmethod
    def _fallback_cause(facts: Dict[str, Any]) -> str:
        deploy = facts.get("recent_deploy")
        if deploy:
            return f"Possibly correlated with recent deployment {deploy['version']}."
        return "No recent deployment correlates; cause requires investigation."

    @staticmethod
    def _fallback_action(severity: IncidentSeverity, facts: Dict[str, Any]) -> str:
        if severity in (IncidentSeverity.SEV1, IncidentSeverity.SEV2):
            deploy = facts.get("recent_deploy")
            if deploy:
                return f"Page the on-call commander and prepare rollback of {deploy['version']}."
            return "Page the on-call commander and open a war room."
        return "Assign to the owning squad during business hours."
