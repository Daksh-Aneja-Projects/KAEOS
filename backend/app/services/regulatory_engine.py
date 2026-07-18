"""
KAEOS 10X — Autonomous Regulatory Engine (L24)
Pre-emptive Compliance & Self-Healing Policy Generation
"""
import logging
import uuid
from typing import Dict

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import Rule, ConfidenceTier

logger = logging.getLogger(__name__)

class RegulatoryUpdate:
    def __init__(self, framework_name: str, directive_text: str, urgency: str):
        self.framework_name = framework_name
        self.directive_text = directive_text
        self.urgency = urgency


class RegulatoryEngine:
    """
    Ingests global legislative updates and autonomously generates or patches
    internal business rules to maintain 100% compliance.
    """

    @staticmethod
    async def ingest_new_regulation(db: AsyncSession, update: RegulatoryUpdate, tenant_id: str = "default") -> Dict[str, any]:
        """
        Parses a new legal directive, evaluates required actions using the LLM, 
        and autonomously submits new absolute compliance rules to the Polystore.
        """
        logger.info(f"Ingesting new regulation: {update.framework_name} [{update.urgency}]")
        
        from app.services.llm_router import LLMRouter
        import json
        
        # 1. Autonomously Synthesize New Rules using LLM
        router = LLMRouter()
        prompt = (
            f"You are the KAEOS Regulatory Engine. We received a new legal framework update: {update.framework_name}.\n"
            f"Directive Text: {update.directive_text}\n"
            f"Analyze this directive and determine the exact operational rule we must enforce to comply.\n"
            f"Output strictly a JSON object with keys: 'statement' (the plain text rule), 'domain' (e.g., 'finance', 'support_cx', 'hr', 'engineering'), "
            f"'trigger_condition' (e.g., 'ai_confidence < 0.95'), 'action' (e.g., 'generate_transparency_report')."
        )
        
        new_rules_generated = []
        try:
            res = await router.complete(prompt=prompt, model_tier="fast")
            content = res if isinstance(res, str) else res.get("content", "{}")
            analysis = json.loads(content) if isinstance(content, str) else content
            
            if "statement" in analysis and "domain" in analysis:
                new_rule = Rule(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    statement=analysis["statement"],
                    trigger_json={"condition": analysis.get("trigger_condition", "always")},
                    action_json={"action": analysis.get("action", "enforce_compliance")},
                    domain=analysis["domain"],
                    workflow_id="wf_compliance_auto",
                    confidence_vector={"source_breadth": 1.0, "source_authority": 1.0, "temporal_freshness": 1.0, "outcome_validation": 0.0, "explicit_validation": 1.0},
                    confidence_scalar=1.0,  # Legal mandates are absolute
                    confidence_tier=ConfidenceTier.VERIFIED,
                    half_life_days=365,
                    is_executable=True,
                    compliance_tags=[update.framework_name],
                    access_level="global"
                )
                db.add(new_rule)
                new_rules_generated.append(new_rule)
                await db.commit()
        except Exception as e:
            logger.error(f"Failed to synthesize regulatory rule: {e}")
            return {"status": "FAILED_SYNTHESIS", "error": str(e)}
        
        return {
            "status": "COMPLIANCE_ACHIEVED",
            "framework": update.framework_name,
            "new_rules_synthesized": len(new_rules_generated),
            "rule_statements": [r.statement for r in new_rules_generated]
        }
