"""
KAEOS Workforce Layer — Domain Pack Loader

Loads and validates YAML domain pack definitions.
"""
import os
import yaml
import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

PACKS_DIR = os.path.join(os.path.dirname(__file__), "packs")


class DomainPackLoader:
    
    @staticmethod
    def load_all_built_in_packs() -> List[Dict[str, Any]]:
        """Loads all YAML files in the packs directory."""
        packs = []
        if not os.path.exists(PACKS_DIR):
            logger.warning(f"Domain packs directory not found: {PACKS_DIR}")
            return packs
            
        for filename in os.listdir(PACKS_DIR):
            if filename.endswith(".yaml") or filename.endswith(".yml"):
                try:
                    with open(os.path.join(PACKS_DIR, filename), "r", encoding="utf-8") as f:
                        pack_data = yaml.safe_load(f)
                        if DomainPackLoader.validate_pack(pack_data):
                            packs.append(pack_data)
                except Exception as e:
                    logger.error(f"Failed to load domain pack {filename}: {e}")
                    
        return packs

    @staticmethod
    def validate_pack(pack: Dict[str, Any]) -> bool:
        """Validates the schema of a loaded domain pack."""
        required_fields = ["name", "slug", "capabilities", "agent_definitions"]
        for field in required_fields:
            if field not in pack:
                logger.error(f"Invalid domain pack: missing required field '{field}'")
                return False
        return True
