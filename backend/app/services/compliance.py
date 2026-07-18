from typing import List, Dict, Any
import logging
from app.services.llm_router import LLMRouter

logger = logging.getLogger(__name__)

class ComplianceEngine:
    """L13 - Regulatory Compliance & Policy Enforcement Engine"""
    
    COMPLIANCE_FRAMEWORKS = {
        "GDPR": "General Data Protection Regulation (EU) - Focus on consent, right to erasure, data minimization, and PII.",
        "HIPAA": "Health Insurance Portability and Accountability Act (US) - Focus on PHI (Protected Health Information), medical records, minimum necessary access.",
        "SOX": "Sarbanes-Oxley Act (US) - Focus on financial controls, audit trails, and strict human approval for financial transactions.",
        "PCI": "Payment Card Industry Data Security Standard - Focus on credit card data, encryption, and strict handling of PANs.",
        "CCPA": "California Consumer Privacy Act (US) - Focus on consumer right to know, right to delete, and opt-out of data sale.",
        "EEOC": "Equal Employment Opportunity Commission (US) - Focus on preventing discrimination based on race, color, religion, sex, national origin, age, disability or genetic info.",
        "I9": "Employment Eligibility Verification (US) - Strict adherence to timeline and document verification for employment authorization."
    }

    async def check_before_execution(self, skill_tags: List[str], context: Dict[str, Any]) -> List[Dict[str, str]]:
        """
        Validates execution context against compliance frameworks before an agent acts.
        Uses LLM reasoning to evaluate context against specific regulatory frameworks.
        """
        violations = []
        if not skill_tags:
            return violations

        router = LLMRouter()
        
        # Hardcoded critical checks that don't need LLM
        for tag in skill_tags:
            if tag == "SOX" and not context.get("has_human_approver"):
                violations.append({
                    "framework": "SOX",
                    "severity": "BLOCKER",
                    "reason": "SOX requires explicit human approval for this financial action."
                })
            elif tag == "PCI" and "raw_card_data" in context:
                violations.append({
                    "framework": "PCI",
                    "severity": "BLOCKER",
                    "reason": "PCI blocks raw card data handling in agent context."
                })

        # LLM-powered contextual checks for complex frameworks (EEOC, GDPR, HIPAA)
        complex_tags = [t for t in skill_tags if t in ["EEOC", "GDPR", "HIPAA", "CCPA", "I9"]]
        if complex_tags:
            framework_descriptions = "\\n".join([f"- {t}: {self.COMPLIANCE_FRAMEWORKS[t]}" for t in complex_tags])
            prompt = f"""
            You are the KAEOS Compliance Engine. Evaluate the following planned agent action for regulatory violations.
            
            Applicable Frameworks:
            {framework_descriptions}
            
            Action Context:
            {context}
            
            Are there any compliance violations or severe risks? Respond ONLY with a JSON list of violation objects:
            [
              {{"framework": "...", "severity": "BLOCKER|WARNING", "reason": "..."}}
            ]
            If no violations, return an empty list: []
            """
            
            try:
                res = await router.complete(prompt=prompt, model_tier="reasoning", temperature=0.1)
                import json
                
                content = res if isinstance(res, str) else res.get("content", "[]")
                # Clean JSON fences
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()
                    
                evaluated_violations = json.loads(content)
                if isinstance(evaluated_violations, list):
                    violations.extend(evaluated_violations)
            except Exception as e:
                logger.error(f"Compliance LLM evaluation failed: {e}")
                # Fail-safe: if we can't verify compliance for complex frameworks, raise a warning
                violations.append({
                    "framework": "SYSTEM",
                    "severity": "WARNING",
                    "reason": f"Could not verify compliance due to system error: {e}"
                })
                
        return violations

    def enforce_audit_requirements(self, skill_tags: List[str], execution_outcome: Dict[str, Any]) -> bool:
        """Ensures post-execution audit requirements are met."""
        for tag in skill_tags:
            if tag == "SOX":
                if not execution_outcome.get("financial_amount_logged"):
                    return False
            if tag == "GDPR":
                if not execution_outcome.get("data_processing_basis_logged"):
                    return False
        return True

