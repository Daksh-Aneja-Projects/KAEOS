from typing import Dict, Any

class BenchmarkEngine:
    """L14 - Cross-Org Benchmark & Industry Intelligence Network"""
    
    def __init__(self, tenant_id: str, industry: str):
        self.tenant_id = tenant_id
        self.industry = industry

    async def generate_intelligence_report(self, department: str, current_coverage: float) -> Dict[str, Any]:
        """Generates the industry intelligence report with generative analysis."""
        from app.services.llm_router import LLMRouter
        import json
        
        router = LLMRouter()
        prompt = (
            f"You are the KAEOS Benchmarking Engine. A tenant in the '{self.industry}' sector has a knowledge coverage of {current_coverage*100:.1f}% for the '{department}' department.\n"
            f"Compare this to typical industry standards. Generate a JSON report with 'industry_p50', 'industry_p90', 'tenant_freshness', 'industry_freshness', 'insight' (1 short sentence), and 'top_gaps' (an array of 2 missing operational playbooks common in the industry)."
        )
        
        try:
            res = await router.complete(prompt=prompt, model_tier="fast")
            content = res if isinstance(res, str) else res.get("content", "{}")
            data = json.loads(content) if isinstance(content, str) else content
            
            return {
                "department": department,
                "industry_segment": f"{self.industry} (Generative Benchmark)",
                "coverage_metrics": {
                    "tenant": current_coverage,
                    "industry_p50": data.get("industry_p50", 0.60),
                    "industry_p90": data.get("industry_p90", 0.85)
                },
                "decay_insight": {
                    "tenant_freshness": data.get("tenant_freshness", 0.70),
                    "industry_freshness": data.get("industry_freshness", 0.75),
                    "insight": data.get("insight", "Coverage is aligned with industry peers.")
                },
                "top_gaps": data.get("top_gaps", ["Unknown gap 1", "Unknown gap 2"])
            }
        except Exception as e:
            import logging
            logging.error(f"Benchmarking engine failed: {e}")
            raise ValueError(f"Generative benchmarking failed: {e}")
