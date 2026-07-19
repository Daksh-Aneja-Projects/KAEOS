"""KAEOS — Fairness Engine (AEOS P3 — Ethical AI & Bias Guardrails)
Demographic fairness scoring for HCM-touching agent actions.
EU AI Act Article 13 + GDPR Article 22 compliant.
"""
import logging
import json
from typing import Optional
from datetime import datetime, timezone

from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.fairness import FairnessAuditLog, FairnessConfig
from app.models.domain import Skill
from app.services.llm_router import LLMRouter

logger = logging.getLogger(__name__)

# Entity types that trigger mandatory fairness checks
# Now dynamically loaded from department config via context.
DEFAULT_PROTECTED_ATTRIBUTES = ["gender", "ethnicity", "age", "disability", "nationality"]
DEFAULT_THRESHOLD = 0.85

class FairnessEngine:
    """Scores agent actions for demographic fairness before execution.
    
    Any action designated by the department config as requiring fairness assessment
    is assessed against protected attributes.
    """

    def __init__(self):
        self.llm = LLMRouter()

    def requires_fairness_check(self, skill: Skill, context: dict) -> bool:
        """Determine if a skill execution needs fairness assessment based on context flags."""
        return context.get("requires_fairness_assessment", False)

    async def score_fairness(
        self,
        skill: Skill,
        context: dict,
        tenant_id: str,
        execution_id: Optional[str] = None,
        blueprint_id: Optional[str] = None,
    ) -> dict:
        """Run fairness assessment and persist audit log.
        
        Returns: { score, passed, flagged_attributes, rationale, audit_log_id }
        """
        # Load tenant config
        config = await self._get_config(tenant_id, skill.department)
        threshold = config.get("threshold", DEFAULT_THRESHOLD)
        attributes = config.get("attributes", DEFAULT_PROTECTED_ATTRIBUTES)

        # Build assessment context dynamically from entity metadata
        action_desc = self._build_action_description(skill, context)
        entity_metadata = context.get("affected_entity_metadata", [])
        if entity_metadata:
            action_desc += f"\n\nAFFECTED ENTITIES (Sample data from Graph): {entity_metadata}"

        # LLM fairness assessment
        assessment = await self._assess_fairness(action_desc, attributes)

        score = assessment.get("overall_score", 0.5)
        passed = score >= threshold
        flagged = assessment.get("flagged_attributes", [])

        # Persist audit log
        log = FairnessAuditLog(
            tenant_id=tenant_id,
            execution_id=execution_id,
            blueprint_id=blueprint_id,
            fairness_score=score,
            threshold_used=threshold,
            passed=passed,
            protected_attributes_assessed=attributes,
            attribute_scores=assessment.get("attribute_scores", {}),
            flagged_attributes=flagged,
            rationale=assessment.get("rationale", "Assessment completed."),
            action_description=action_desc,
            affected_entity_type=context.get("affected_entity_type", "Employee"),
            affected_entity_count=context.get("affected_count", 0),
        )

        async with AsyncSessionLocal() as session:
            session.add(log)
            await session.commit()
            await session.refresh(log)

        status = "PASSED" if passed else "BLOCKED"
        logger.info(f"[Fairness] {status}: score={score:.2f} threshold={threshold} flagged={flagged}")

        return {
            "score": score,
            "passed": passed,
            "flagged_attributes": flagged,
            "rationale": assessment.get("rationale", ""),
            "attribute_scores": assessment.get("attribute_scores", {}),
            "audit_log_id": log.id,
        }

    async def override_block(
        self, log_id: str, tenant_id: str, override_by: str, justification: str
    ) -> dict:
        """Override a fairness block with justification (audited)."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(FairnessAuditLog).where(
                    FairnessAuditLog.id == log_id,
                    FairnessAuditLog.tenant_id == tenant_id,
                )
            )
            log = result.scalar_one_or_none()
            if not log:
                raise ValueError(f"Fairness audit log {log_id} not found")

            log.was_overridden = True
            log.override_by = override_by
            log.override_justification = justification
            log.override_at = datetime.now(timezone.utc)
            await session.commit()

            logger.warning(f"[Fairness] OVERRIDE: log={log_id} by={override_by}")
            return {"status": "overridden", "log_id": log_id}

    async def _get_config(self, tenant_id: str, department: Optional[str] = None) -> dict:
        """Get fairness config for tenant/department."""
        async with AsyncSessionLocal() as session:
            # Try department-specific first
            if department:
                result = await session.execute(
                    select(FairnessConfig).where(
                        FairnessConfig.tenant_id == tenant_id,
                        FairnessConfig.department == department,
                    )
                )
                config = result.scalar_one_or_none()
                if config:
                    return {
                        "threshold": config.fairness_threshold,
                        "attributes": config.protected_attributes,
                        "allow_override": config.allow_override,
                    }

            # Fall back to org-wide
            result = await session.execute(
                select(FairnessConfig).where(
                    FairnessConfig.tenant_id == tenant_id,
                    FairnessConfig.department == None,  # noqa: E711
                )
            )
            config = result.scalar_one_or_none()
            if config:
                return {
                    "threshold": config.fairness_threshold,
                    "attributes": config.protected_attributes,
                    "allow_override": config.allow_override,
                }

        return {"threshold": DEFAULT_THRESHOLD, "attributes": DEFAULT_PROTECTED_ATTRIBUTES, "allow_override": True}

    def _build_action_description(self, skill: Skill, context: dict) -> str:
        steps = ", ".join(s.get("action", "?") for s in (skill.steps or [])[:5])
        return f"Skill '{skill.skill_id}' in {skill.department}/{skill.domain}: {steps}. Intent: {context.get('intent', 'N/A')}"

    async def _assess_fairness(self, action_desc: str, attributes: list) -> dict:
        """Use LLM to assess fairness impact across protected attributes."""
        try:
            prompt = f"""You are an AI Ethics & Fairness assessor for enterprise HCM systems.
Assess the following action for potential disparate impact on protected demographic groups.

ACTION: {action_desc}

PROTECTED ATTRIBUTES TO ASSESS: {', '.join(attributes)}

For each attribute, score 0.0-1.0 (1.0 = perfectly fair, 0.0 = severe bias risk).
Flag any attribute scoring below 0.85.

Respond in JSON:
{{"overall_score": 0.0-1.0, "attribute_scores": {{"gender": {{"score": 0.9, "flag": false}}}}, "flagged_attributes": ["age"], "rationale": "Plain language explanation suitable for regulators"}}"""

            resp = await self.llm.complete(prompt=prompt, model_tier="reasoning", temperature=0.2)
            from app.services.json_utils import extract_json_object
            return extract_json_object(resp)
        except Exception as e:
            logger.error(f"[Fairness] Assessment failed: {e}")
            # FAIL CLOSED: an unassessable action is not a safe action. Score 0.0
            # so the gate blocks (or routes to a human) rather than passing on an
            # unverifiable neutral score. This is the correct behaviour when the
            # LLM provider is unavailable (NoLLMProviderError) in production.
            return {
                "overall_score": 0.0,
                "attribute_scores": {},
                "flagged_attributes": ["assessment_error"],
                "rationale": f"Fairness assessment could not be completed ({str(e)}). "
                             f"Blocking per fail-closed policy.",
            }
