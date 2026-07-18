from typing import Dict, Any, List, Optional
import json


def _parse_llm_json(content: str) -> Optional[Dict[str, Any]]:
    """Best-effort JSON extraction from an LLM reply (fences, leading prose)."""
    if not isinstance(content, str):
        return content if isinstance(content, dict) else None
    text = content.strip()
    if "```" in text:
        parts = text.split("```")
        for part in parts[1:]:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{"):
                text = part
                break
    if "{" in text and "}" in text:
        text = text[text.find("{"): text.rfind("}") + 1]
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except (ValueError, TypeError):
        return None


class ContradictionDetector:
    """L2 - Knowledge Extraction Engine (Conflict sub-system)"""

    MAX_COMPARISONS = 10  # bound LLM prompt size — most-relevant rules first

    async def detect(self, candidate_rule: Dict[str, Any], existing_kb: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Detects if a new candidate rule contradicts the existing KB via Semantic Evaluation.

        One batched LLM call covers all same-domain rules — a per-rule loop of
        sequential completions was unusably slow on local models.
        """
        from app.services.llm_router import LLMRouter
        import logging
        logger = logging.getLogger(__name__)

        same_domain = [r for r in existing_kb if r.get('domain') == candidate_rule.get('domain')]
        same_domain = same_domain[: self.MAX_COMPARISONS]
        if not same_domain:
            return {"conflict": False, "type": "INDEPENDENT", "action": "ADD_TO_KB"}

        numbered = "\n".join(
            f"{i + 1}. {r.get('statement')} (Trigger: {r.get('trigger_json')}, Action: {r.get('action_json')})"
            for i, r in enumerate(same_domain)
        )
        prompt = (
            f"A new business rule is being added to a knowledge base. Compare it against the existing rules.\n\n"
            f"NEW RULE: {candidate_rule.get('statement')} "
            f"(Trigger: {candidate_rule.get('trigger_json')}, Action: {candidate_rule.get('action_json')})\n\n"
            f"EXISTING RULES:\n{numbered}\n\n"
            f"Does the new rule directly contradict or overlap in scope with any existing rule?\n"
            f"Return ONLY JSON: {{\"conflict\": true/false, \"conflicting_rule_number\": <1-based number or null>, "
            f"\"type\": \"DIRECT_CONTRADICTION\" or \"SCOPE_OVERLAP\" or \"NONE\", "
            f"\"action\": \"BLOCK_AND_ESCALATE\" or \"MERGE\" or \"ADD_TO_KB\"}}"
        )

        try:
            router = LLMRouter()
            res = await router.complete(prompt=prompt, model_tier="fast")
            content = res if isinstance(res, str) else res.get("content", "{}")
        except Exception as e:
            logger.warning(f"Semantic conflict check LLM call failed: {e}")
            return {"conflict": False, "type": "INDEPENDENT", "action": "ADD_TO_KB",
                    "degraded_checks": len(same_domain)}

        analysis = _parse_llm_json(content)
        if analysis is None:
            logger.warning(f"Semantic conflict check returned non-JSON: {str(content)[:120]}")
            return {"conflict": False, "type": "INDEPENDENT", "action": "ADD_TO_KB",
                    "degraded_checks": len(same_domain)}

        if analysis.get("conflict"):
            idx = analysis.get("conflicting_rule_number")
            conflicting_id = None
            if isinstance(idx, int) and 1 <= idx <= len(same_domain):
                conflicting_id = same_domain[idx - 1].get('id')
            return {
                "conflict": True,
                "type": analysis.get("type", "DIRECT_CONTRADICTION"),
                "conflicting_rule_id": conflicting_id,
                "action": analysis.get("action", "BLOCK_AND_ESCALATE")
            }

        return {"conflict": False, "type": "INDEPENDENT", "action": "ADD_TO_KB"}

class RuleMiner:
    """L2 - Rule Mining Sub-Engine"""
    
    async def extract_rule(self, signal_cluster: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Uses LLM to articulate a rule from a cluster of signals."""
        from app.services.llm_router import LLMRouter
        
        if len(signal_cluster) < 3:
            return None # Minimum cluster size not met
            
        router = LLMRouter()
        
        signals_text = "\n".join([f"- {s.get('clean_payload', str(s))}" for s in signal_cluster])
        prompt = (
            f"You are the KAEOS Rule Miner. Analyze this cluster of historical events/signals and extract the underlying business rule.\n"
            f"Signals:\n{signals_text}\n"
            f"Output JSON format strictly: {{\"statement\": \"plain text rule\", \"trigger_json\": {{\"condition\": \"X\"}}, \"action_json\": {{\"action\": \"Y\"}}}}"
        )
        
        try:
            res = await router.complete(prompt=prompt, model_tier="classification")
            content = res if isinstance(res, str) else res.get("content", "{}")
            rule_data = json.loads(content) if isinstance(content, str) else content
            rule_data["confidence_basis"] = f"{len(signal_cluster)} consistent instances"
            return rule_data
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"RuleMiner extraction failed: {e}")
            return None
