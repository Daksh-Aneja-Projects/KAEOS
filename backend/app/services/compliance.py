from typing import List, Dict, Any
import logging
from app.services.llm_router import get_tenant_router
from app.services.json_utils import extract_json_list

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

        # 1) Deterministic statutory checkers first (no LLM). A framework with a
        # registered checker is judged by real rules, not a model's opinion; a
        # BLOCK becomes a blocker, an ADVISORY a warning. Tags without a checker
        # fall through to the hardcoded/LLM paths below.
        from app.compliance.base import CheckResult, CheckStatus
        from app.compliance.registry import get as _get_checker
        deterministic_tags = set()
        for tag in skill_tags:
            entry = _get_checker(tag)
            if entry is None:
                continue
            deterministic_tags.add(tag)
            try:
                res = entry.fn(context or {})
                if not isinstance(res, CheckResult):
                    raise TypeError("checker did not return CheckResult")
            except Exception as e:  # a broken control fails closed
                logger.exception("Deterministic %s checker failed", tag)
                violations.append({"framework": tag, "severity": "BLOCKER",
                                   "reason": f"{tag} control failed to evaluate: {e}",
                                   "method": "deterministic"})
                continue
            reason = "; ".join(f.message for f in res.findings)
            if res.status == CheckStatus.BLOCK:
                violations.append({"framework": tag, "severity": "BLOCKER",
                                   "reason": reason or f"{tag} violation",
                                   "method": "deterministic", "citations": res.citations})
            elif res.status == CheckStatus.ADVISORY:
                violations.append({"framework": tag, "severity": "WARNING",
                                   "reason": reason or f"{tag} advisory",
                                   "method": "deterministic", "citations": res.citations})

        # 2) Hardcoded critical checks for tags without a deterministic checker.
        # PCI is written three ways in the wild (PCI / PCI-DSS / PCI_DSS); the
        # shipped support pack tags skills "PCI-DSS", so an exact "PCI" match let
        # raw card data through under the real-world tag. Normalize the family.
        _PCI = {"PCI", "PCI-DSS", "PCI_DSS"}
        pci_tags = set()
        for tag in skill_tags:
            if tag in deterministic_tags:
                continue
            if tag in _PCI:
                pci_tags.add(tag)
                if "raw_card_data" in context:
                    violations.append({
                        "framework": tag,
                        "severity": "BLOCKER",
                        "reason": "PCI blocks raw card data handling in agent context."
                    })

        # 3) LLM-screening fallback ONLY for complex frameworks that have no
        # deterministic checker yet (labeled as screening, not a statutory test).
        complex_tags = [t for t in skill_tags
                        if t in ["GDPR", "HIPAA", "CCPA"] and t not in deterministic_tags]
        if complex_tags:
            # Tenant-aware router so a tenant's fine-tuned compliance model is used.
            router = await get_tenant_router()
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
                content = res if isinstance(res, str) else res.get("content", "[]")
                evaluated_violations = extract_json_list(content)
                violations.extend(evaluated_violations)
            except Exception as e:
                logger.error(f"Compliance LLM evaluation failed: {e}")
                # FAIL CLOSED in a production posture: if we cannot verify
                # compliance (e.g. no LLM provider reachable) the safe answer is
                # to BLOCK, not to proceed on an unverified action. In DEV_MODE /
                # ALLOW_SIMULATED_LLM we downgrade to a WARNING so local work is
                # not gridlocked.
                from app.core.config import get_settings
                unverifiable_is_blocking = not get_settings().simulated_llm_allowed
                violations.append({
                    "framework": "SYSTEM",
                    "severity": "BLOCKER" if unverifiable_is_blocking else "WARNING",
                    "reason": f"Could not verify compliance due to system error: {e}"
                })

        # 4) Fail-closed honesty: any tag that was neither judged deterministically,
        # covered by the PCI raw-card guard, nor LLM-screened is NOT verified. Emit
        # a WARNING so it can never SILENTLY pass (matching registry.run_checks'
        # UNBACKED posture) - a posture tag like SOC2/ISO-27001/PCI-DSS must surface
        # in the result and provenance, not vanish. WARNING (not BLOCKER) so a
        # legitimately unbacked tag like GAAP does not gridlock every action.
        covered = deterministic_tags | pci_tags | set(complex_tags)
        for tag in skill_tags:
            if tag in covered:
                continue
            violations.append({
                "framework": tag,
                "severity": "WARNING",
                "reason": f"No deterministic checker backs '{tag}'; this compliance "
                          "claim is not verified.",
                "method": "registry",
            })

        return violations

    def enforce_audit_requirements(self, skill_tags: List[str], execution_outcome: Dict[str, Any]) -> bool:
        """Ensure post-execution audit requirements are met.

        Not a checkbox: for each regulated tag we require BOTH the "logged" flag
        AND the actual audited datum to be present in the outcome. A flag set
        without the underlying value (a financial amount for SOX, a lawful basis
        for GDPR/HIPAA) does not satisfy the audit — the trail must carry the fact,
        not just an assertion that it was logged.
        """
        for tag in skill_tags:
            if tag == "SOX":
                if not execution_outcome.get("financial_amount_logged"):
                    return False
                if execution_outcome.get("amount") in (None, ""):
                    return False
            if tag in ("GDPR", "HIPAA", "CCPA"):
                if not execution_outcome.get("data_processing_basis_logged"):
                    return False
                if not execution_outcome.get("legal_basis"):
                    return False
        return True

