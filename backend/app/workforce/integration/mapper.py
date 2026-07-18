"""
KAEOS Workforce Layer — Integration Mapper

Maps external connector data to standard internal capabilities.
Uses the LLM to auto-detect schema mappings.
"""
import logging
from app.services.llm_router import LLMRouter

logger = logging.getLogger(__name__)

class IntegrationMapper:
    """Handles mapping of external data (e.g. Workday) to KAEOS capabilities."""
    
    @staticmethod
    async def auto_map_schema(source_schema: dict, target_capability: str) -> dict:
        """
        Uses LLM to automatically map an external schema to the KAEOS internal schema.
        """
        logger.info(f"Auto-mapping schema for capability {target_capability}")
        router = LLMRouter()
        
        prompt = f"""
        You are the KAEOS Data Mapper. We need to map an external system's data to our internal capability: {target_capability}.
        
        External Schema:
        {source_schema}
        
        Suggest a field mapping. Output ONLY valid JSON in this format:
        {{
            "mappings": {{
                "external_field": "internal_field"
            }},
            "confidence": 0.95
        }}
        """
        
        try:
            res = await router.complete(prompt=prompt, model_tier="fast")
            import json
            
            content = res if isinstance(res, str) else res.get("content", "{}")
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
                
            return json.loads(content)
        except Exception as e:
            logger.error(f"Auto-mapping failed: {e}")
            return {"mappings": {}, "confidence": 0.0}
