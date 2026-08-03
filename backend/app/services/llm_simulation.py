"""
KAEOS L9 — deterministic simulated completions.

When no LLM provider is reachable (no keys, no Ollama) the router degrades to a
deterministic simulated response instead of raising, keeping the dev stack
runnable with no external services. The payload shape is chosen by sniffing
keywords in the prompt so every downstream JSON parser tolerates it. Every
simulated payload is flagged ``"simulated": True``.

Extracted from ``llm_router`` (was ``LLMRouter._simulated_completion``); it is a
pure function of (prompt, system_prompt), so it lives here as module-level code.
"""
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def simulated_completion(prompt: str, system_prompt: Optional[str]) -> dict:
    """Build a deterministic simulated completion whose JSON content matches
    the shape the calling engine expects. Content is chosen by sniffing
    keywords in the prompt so every downstream parser tolerates it.
    """
    p = (prompt or "").lower()
    sys_p = (system_prompt or "").lower()

    # Compliance engine expects a JSON *list* of violations. Simulated =
    # no violations (empty list) so degraded runs are not falsely blocked.
    if "compliance engine" in p or "violation objects" in p or "regulatory violations" in p:
        content = "[]"
    # Fairness assessor expects an object with overall_score.
    elif "fairness" in p or "overall_score" in p or "protected attributes" in p:
        content = json.dumps({
            "overall_score": 0.95,
            "attribute_scores": {},
            "flagged_attributes": [],
            "rationale": "SIMULATED: no LLM provider available; neutral pass.",
            "simulated": True,
        })
    # Debate proposer.
    elif "proposer agent" in p:
        content = json.dumps({
            "evidence": ["SIMULATED evidence 1", "SIMULATED evidence 2", "SIMULATED evidence 3"],
            "conclusion": "SIMULATED: proceed (no provider).",
            "confidence": 0.9,
            "grounded_in": ["simulated"],
            "simulated": True,
        })
    # Debate devil's advocate. (Match only the unique role header — the
    # arbitrator prompt embeds the advocate's JSON, so do NOT match on keys
    # like "counter_evidence".)
    elif "devil's advocate" in p:
        content = json.dumps({
            "counter_evidence": [],
            "risks": [],
            "conclusion": "SIMULATED: no material risk found (no provider).",
            "ungrounded_claims_found": 0,
            "simulated": True,
        })
    # Debate arbitrator.
    elif "arbitrator" in p:
        content = json.dumps({
            "final_confidence": 0.9,
            "rationale": "SIMULATED: no provider available; defaulting to PROCEED.",
            "decision": "PROCEED",
            "weight_proposer": 0.5,
            "weight_advocate": 0.5,
            "simulated": True,
        })
    # Skill router intent classification.
    elif "selected_skill_id" in p:
        content = json.dumps({"selected_skill_id": "NONE", "confidence": 0.0, "simulated": True})
    # Cross-domain perspective.
    elif "perspective" in p and "position" in p:
        content = json.dumps({"perspective": "SIMULATED", "position": "SIMULATED position (no provider)."})
    elif "synthesis" in p and "recommendation" in p:
        content = json.dumps({"synthesis": "SIMULATED synthesis (no provider).", "recommendation": "PROCEED"})
    # Skill execution step (from skill_executor).
    elif "execution engine" in sys_p or '"step_id"' in prompt or "execute this step" in p:
        content = json.dumps({
            "status": "SUCCESS",
            "tool_called": None,
            "tool_result": None,
            "decision": "SIMULATED step execution (no LLM provider).",
            "confidence": 0.9,
            "side_effects": [],
            "error": None,
            "simulated": True,
        })
    else:
        # Generic fallback object.
        content = json.dumps({
            "result": "SIMULATED response — no LLM provider configured.",
            "simulated": True,
        })

    logger.info("[LLM] No provider available — returning SIMULATED completion.")
    return {
        "content": content,
        "model": "simulated",
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "simulated": True,
    }
