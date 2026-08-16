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


def _dangling_process_ids(pack: Dict[str, Any]) -> set:
    """Capability-referenced process ids that have no matching process_definition.

    The generator silently skips these at deploy, so the department ends up with
    fewer processes than its capabilities advertise and any governance rule keyed
    on the id becomes dead code. Surfacing them is the standing to-author list.
    """
    defined = {p.get("id") for p in pack.get("process_definitions", [])}
    referenced = {
        pid for cap in pack.get("capabilities", []) for pid in cap.get("processes", [])
    }
    return referenced - defined


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
        # Warn (do NOT reject) on capability processes with no process_definition:
        # rejecting would drop the whole department, which is worse than deploying
        # the defined subset. This makes the gap observable instead of silent.
        dangling = _dangling_process_ids(pack)
        if dangling:
            logger.warning(
                "Domain pack '%s': %d capability process id(s) have no "
                "process_definition and will be skipped at deploy: %s",
                pack.get("slug"), len(dangling), ", ".join(sorted(dangling)),
            )
        return True


if __name__ == "__main__":
    _p = {
        "capabilities": [{"processes": ["a", "b"]}, {"processes": ["b", "c"]}],
        "process_definitions": [{"id": "a"}],
    }
    assert _dangling_process_ids(_p) == {"b", "c"}, "dangling detection broken"
    print("loader self-check ok")
