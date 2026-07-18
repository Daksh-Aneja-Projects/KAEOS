"""
Model Capability Probe — BYOK self-calibration.

When a tenant plugs in their own model, KAEOS does not assume it is as capable
as the model we developed against. It probes the model with a small battery of
deterministic checks and stores a capability profile. The governance gates then
adapt: a weaker model earns a lower confidence ceiling, which mechanically
routes more of its decisions to human review.

This is what makes "bring your own model" a governance dial rather than a
quality lottery.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Probe battery. Each probe has a prompt and a grader returning 0.0-1.0.
# Kept small and cheap: the whole battery should run in well under a minute.


def _grade_json_object(raw: str) -> float:
    """Did the model return a parseable JSON object with the requested keys?"""
    from app.services.json_utils import extract_json_object

    try:
        obj = extract_json_object(raw)
    except ValueError:
        return 0.0
    if not isinstance(obj, dict):
        return 0.2
    have = {k.lower() for k in obj.keys()}
    wanted = {"name", "count", "active"}
    hit = len(have & wanted) / len(wanted)
    # Full marks only when the raw output was clean JSON (no prose/fences).
    clean = raw.strip().startswith("{") and raw.strip().endswith("}")
    return round(hit * (1.0 if clean else 0.75), 3)


def _grade_arithmetic(raw: str) -> float:
    """Multi-step reasoning: 3 vendors, 20% discount on the largest."""
    nums = re.findall(r"\d[\d,]*\.?\d*", (raw or "").replace(",", ""))
    return 1.0 if any(abs(float(n) - 36000.0) < 1.0 for n in nums if n) else 0.0


def _grade_instruction(raw: str) -> float:
    """Strict instruction following: exactly one word, uppercase, no punctuation."""
    t = (raw or "").strip()
    if not t:
        return 0.0
    if t == "APPROVED":
        return 1.0
    if t.upper().replace(".", "").strip() == "APPROVED":
        return 0.5  # right answer, sloppy compliance
    return 0.0


PROBES: List[Dict[str, Any]] = [
    {
        "id": "json_compliance",
        "prompt": (
            'Return ONLY a JSON object, no prose and no markdown fences, with exactly these keys: '
            '"name" (string "acme"), "count" (number 3), "active" (boolean true).'
        ),
        "grader": _grade_json_object,
        "max_tokens": 120,
    },
    {
        "id": "reasoning_depth",
        "prompt": (
            "Three vendor invoices are due: $12,000, $45,000 and $8,000. "
            "Apply a 20% discount to the largest invoice only, then report the new total "
            "of all three invoices. Answer with the number."
        ),
        "grader": _grade_arithmetic,
        "max_tokens": 400,
    },
    {
        "id": "instruction_following",
        "prompt": (
            "Reply with exactly one word, in uppercase, with no punctuation and no explanation: "
            "the word APPROVED."
        ),
        "grader": _grade_instruction,
        "max_tokens": 20,
    },
]

# Weighted contribution of each probe to the tier ceiling.
_WEIGHTS = {
    "json_compliance": 0.4,       # structured output underpins every gate
    "reasoning_depth": 0.4,       # multi-step judgement
    "instruction_following": 0.2, # guardrail adherence
}


class ModelProbe:
    """Runs the capability battery against a tenant's configured model."""

    async def run(
        self,
        model_name: str,
        api_key: Optional[str] = None,
        provider: Optional[str] = None,
        api_base: Optional[str] = None,
    ) -> Dict[str, Any]:
        from app.services.llm_router import LLMRouter

        tenant_keys: Dict[str, Any] = {}
        if api_key and provider:
            tenant_keys[provider.lower()] = api_key
        if api_base:
            tenant_keys["custom_base_url"] = api_base

        router = LLMRouter()
        scores: Dict[str, float] = {}
        latencies: List[float] = []
        errors: List[str] = []

        for probe in PROBES:
            started = time.perf_counter()
            try:
                res = await router.complete(
                    prompt=probe["prompt"],
                    model=model_name,
                    temperature=0.0,
                    max_tokens=probe["max_tokens"],
                    tenant_api_keys=tenant_keys or None,
                )
                content = res if isinstance(res, str) else res.get("content", "")
                # A simulated response means no provider was reachable — that is
                # an unusable model, not a capable one. Score it zero.
                if isinstance(res, dict) and res.get("simulated"):
                    scores[probe["id"]] = 0.0
                    errors.append(f"{probe['id']}: no provider reachable (simulated)")
                else:
                    scores[probe["id"]] = float(probe["grader"](content))
            except Exception as e:
                scores[probe["id"]] = 0.0
                errors.append(f"{probe['id']}: {type(e).__name__}: {e}")
            latencies.append((time.perf_counter() - started) * 1000)

        tier_ceiling = round(
            sum(scores.get(k, 0.0) * w for k, w in _WEIGHTS.items()), 3
        )

        profile = {
            **{k: round(v, 3) for k, v in scores.items()},
            "tier_ceiling": tier_ceiling,
            "latency_ms": int(sum(latencies) / len(latencies)) if latencies else 0,
            "probed_at": datetime.now(timezone.utc).isoformat(),
            "model_name": model_name,
            "usable": tier_ceiling > 0.0,
            "errors": errors,
            "recommendation": self._recommendation(tier_ceiling),
        }
        logger.info(
            f"[ModelProbe] {model_name} → ceiling={tier_ceiling} "
            f"json={scores.get('json_compliance')} reason={scores.get('reasoning_depth')}"
        )
        return profile

    @staticmethod
    def _recommendation(ceiling: float) -> str:
        if ceiling >= 0.85:
            return "Suitable for autonomous execution up to the standard 0.82 HITL threshold."
        if ceiling >= 0.6:
            return (
                "Reduced autonomy: confidence is capped, so more decisions route to human review. "
                "Suitable for assisted workflows."
            )
        if ceiling > 0.0:
            return (
                "Low capability: nearly all decisions will require human approval. "
                "Use a stronger model for autonomous tiers."
            )
        return "Unusable: the model did not respond or failed every probe. Check the key, model id, and base URL."


model_probe = ModelProbe()
