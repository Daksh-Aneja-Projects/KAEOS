"""Helpers shared by more than one HR sub-router."""
from typing import Any, Dict, Optional


def _exec_id(result: Dict[str, Any]) -> Optional[str]:
    """Gated-executor results carry execution_id at top level when clean, or
    nested under 'detail' when gated — same shape trigger_screening handles."""
    return result.get("execution_id") or (result.get("detail") or {}).get("execution_id")
