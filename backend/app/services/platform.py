from typing import Dict, Any, List
import uuid
import json

class ExplainabilityEngine:
    """L15 - Explainability & Audit Reasoning Layer"""

    async def explain_action(self, execution_chain: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Generates human-readable explanations for agent actions."""
        from app.services.llm_router import LLMRouter

        router = LLMRouter()
        prompt = (
            f"You are the KAEOS Explainability Engine. Analyze this agent execution chain and provide a 1-sentence plain-english summary of why the action was taken.\n"
            f"Chain: {json.dumps(execution_chain)}\n"
            f"Output JSON: {{\"summary\": \"...\", \"confidence_narrative\": \"...\"}}"
        )

        try:
            from app.services.json_utils import extract_json_object

            res = await router.complete(prompt=prompt, model_tier="classification")
            content = res if isinstance(res, str) else res.get("content", "{}")
            analysis = extract_json_object(content)
            return {
                "summary": analysis.get("summary", "Action was executed based on the provided rules."),
                "steps_taken": execution_chain,
                "confidence_narrative": analysis.get("confidence_narrative", "Confidence derived from rule chain."),
                "human_validators": []
            }
        except Exception as e:
            # Degrade to a deterministic explanation — the audit surface must
            # stay available even when the generative model is down or chatty.
            import logging
            logging.error(f"Explainability engine failed, using deterministic fallback: {e}")
            return {
                "summary": "Action was executed based on the recorded rule chain.",
                "steps_taken": execution_chain,
                "confidence_narrative": "Deterministic fallback — generative explanation unavailable.",
                "human_validators": [],
                "degraded": True,
            }

class ConflictResolutionArena:
    """L16 - Real-Time Collaboration & Conflict Resolution Arena"""
    
    async def open_conflict_arena(self, rule_a_id: str, rule_b_id: str, tenant_id: str = "default") -> str:
        """Opens a structured async debate workspace for conflicting rules."""
        from app.core.database import AsyncSessionLocal
        from app.models.domain import ConflictCase
        
        async with AsyncSessionLocal() as db:
            arena_id = str(uuid.uuid4())
            conflict = ConflictCase(
                id=arena_id,
                tenant_id=tenant_id,
                rule_a_id=rule_a_id,
                rule_b_id=rule_b_id,
                conflict_type="DETECTED_BY_ENGINE",
                severity="MODERATE",
                status="OPEN"
            )
            db.add(conflict)
            await db.commit()
            
        return arena_id
        
    async def resolve_conflict(self, arena_id: str, resolution_type: str, resolution_note: str):
        """Commits the resolution back to the KB."""
        from app.core.database import AsyncSessionLocal
        from app.models.domain import ConflictCase
        from datetime import datetime, timezone
        
        async with AsyncSessionLocal() as db:
            conflict = await db.get(ConflictCase, arena_id)
            if conflict:
                conflict.status = "RESOLVED"
                conflict.resolution_type = resolution_type
                conflict.resolution_note = resolution_note
                conflict.resolved_at = datetime.now(timezone.utc)
                db.add(conflict)
                await db.commit()

class MarketplacePlatform:
    """L19 - Developer Platform & Marketplace"""
    
    async def publish_skill_template(self, skill_contract: Dict[str, Any], author: str) -> str:
        """Publishes an anonymized skill to the public marketplace."""
        from app.core.database import AsyncSessionLocal
        from app.models.domain import MarketplaceTemplate
        
        async with AsyncSessionLocal() as db:
            template = MarketplaceTemplate(
                id=str(uuid.uuid4()),
                name=skill_contract.get("skill_id", "Unknown Skill"),
                category=skill_contract.get("domain", "General"),
                description=f"Automated template published by {author}",
                author=author,
                status="PUBLISHED"
            )
            db.add(template)
            await db.commit()
            
        return template.id
