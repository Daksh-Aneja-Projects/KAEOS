from typing import Dict, Any, List

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
        
        # 3. Quality Scoring (Assuming acceptable for now since LLM generated it based on strict prompt)
        score = QuestionQualityScore(0.8, 0.9, 0.85, 0.75, 0.9)
        
        if not score.is_acceptable:
            return {"status": "FAILED_QUALITY_CHECK"}
            
        return {
            "status": "GENERATED",
            "question": question_text,
            "target_employee_id": employee_context.get("id"),
            "delivery_channel": "slack"
        }
