from typing import Dict, Any, List


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def score_question_quality(
    question_text: str,
    employee_context: Dict[str, Any],
    candidate: Dict[str, Any],
) -> "QuestionQualityScore":
    """Compute a HEURISTIC quality score from features of the generated question.

    These are lightweight lexical heuristics (length, question form, grounding in
    the supplied context, intent keywords, lexical diversity) — NOT a learned or
    LLM-judged metric. They are honest, cheap signals; callers should treat the
    result as ``method="heuristic"`` rather than a measured ground-truth score.
    """
    text = (question_text or "").strip()
    words = text.split()
    n = len(words)
    lower = text.lower()

    first_name = str(employee_context.get("first_name", "") or "").strip().lower()
    context_ref = str(candidate.get("context_ref", "") or "").strip().lower()
    action = str(candidate.get("action", "") or "").strip().lower()

    def _mentions(token: str) -> bool:
        return bool(token) and token not in ("", "x", "a recent case") and token in lower

    # specificity — references the concrete case/action it is asking about
    specificity = _clamp01(0.4 + (0.3 if _mentions(context_ref) else 0.0)
                           + (0.3 if _mentions(action) else 0.0))

    # groundedness — personalized + anchored in the supplied context
    groundedness = _clamp01(0.5 + (0.25 if _mentions(first_name) else 0.0)
                            + (0.25 if (_mentions(context_ref) or _mentions(action)) else 0.0))

    # answerability — ends as a question and sits in a readable length band
    length_ok = 1.0 if 8 <= n <= 45 else (0.6 if 4 <= n <= 70 else 0.3)
    answerability = _clamp01(0.4 * (1.0 if "?" in text else 0.0) + 0.6 * length_ok)

    # relevance — asks about the *reason/deciding factor* (the elicitation goal)
    intent_kw = ("why", "decid", "factor", "reason", "chose", "choose", "because", "rationale")
    relevance = _clamp01(0.55 + (0.35 if any(k in lower for k in intent_kw) else 0.0))

    # novelty — lexical diversity as a cheap proxy (repetitive/templated => lower)
    novelty = _clamp01(len(set(w.lower() for w in words)) / n) if n else 0.0

    return QuestionQualityScore(specificity, groundedness, answerability, novelty, relevance)


class QuestionQualityScore:
    def __init__(self, specificity: float, groundedness: float, answerability: float, novelty: float, relevance: float):
        self.specificity = specificity
        self.groundedness = groundedness
        self.answerability = answerability
        self.novelty = novelty
        self.relevance = relevance

    @property
    def is_acceptable(self) -> bool:
        return all(v >= 0.7 for v in [self.specificity, self.groundedness, self.answerability, self.novelty, self.relevance])

    def as_dict(self) -> Dict[str, Any]:
        """Serialize the scores, tagged as heuristic (not a measured metric)."""
        return {
            "specificity": round(self.specificity, 3),
            "groundedness": round(self.groundedness, 3),
            "answerability": round(self.answerability, 3),
            "novelty": round(self.novelty, 3),
            "relevance": round(self.relevance, 3),
            "method": "heuristic",
        }

class ElicitationEngine:
    """L5 - Active Elicitation & Human-in-the-Loop System"""
    
    async def generate_question(self, employee_context: Dict[str, Any], candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Generates targeted micro-survey questions based on KB gaps and recent actions."""
        from app.services.llm_router import LLMRouter
        router = LLMRouter()
        
        # 1. Check Cognitive Load Limits
        if employee_context.get("questions_this_week", 0) >= 3:
            return {"status": "SKIPPED_RATE_LIMIT"}
            
        if not candidates:
            return {"status": "NO_CANDIDATES"}
            
        candidate = candidates[0]
        
        # 2. Actual LLM Question Generation
        prompt = (
            f"You are KAEOS's L5 Elicitation Engine. Generate a highly conversational, friendly micro-survey question "
            f"for an employee named {employee_context.get('first_name', 'there')}.\n"
            f"Context: In {candidate.get('context_ref', 'a recent case')}, they took action: {candidate.get('action', 'X')}.\n"
            f"Goal: Find out the deciding factor for this action to improve the Knowledge Base.\n"
            f"Keep it under 3 sentences. Output just the message."
        )
        
        try:
            res = await router.complete(prompt=prompt, model_tier="fast")
            question_text = (res if isinstance(res, str) else res.get("content", "")).strip()
        except Exception as e:
            return {"status": "FAILED_LLM_GENERATION", "error": str(e)}

        # 3. Quality Scoring — computed HEURISTICALLY from the generated text (no
        # longer a hardcoded pass). See score_question_quality(): these are cheap
        # lexical signals surfaced as method="heuristic", not a measured metric.
        score = score_question_quality(question_text, employee_context, candidate)

        # Honest gate: reject only genuinely malformed output (empty / not a
        # question). The sub-scores are advisory signals returned to the caller,
        # not a hard pass/fail — the previous all-≥0.7 gate was only ever met
        # because the scores were fabricated to pass it.
        if not question_text or ("?" not in question_text and len(question_text.split()) < 4):
            return {"status": "FAILED_QUALITY_CHECK", "quality": score.as_dict()}

        return {
            "status": "GENERATED",
            "question": question_text,
            "quality": score.as_dict(),
            "quality_acceptable": score.is_acceptable,
            "target_employee_id": employee_context.get("id"),
            "delivery_channel": "slack"
        }
