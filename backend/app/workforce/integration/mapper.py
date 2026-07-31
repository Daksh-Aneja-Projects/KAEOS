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
            from app.services.json_utils import extract_json_object

            content = res if isinstance(res, str) else res.get("content", "{}")
            return extract_json_object(content)
        except Exception as e:
            logger.error(f"Auto-mapping failed: {e}")
            return {"mappings": {}, "confidence": 0.0}
