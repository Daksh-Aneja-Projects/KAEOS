"""
KAEOS Operations Domain — Facility Agent
"""
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class FacilityAgent:
    """Agent for monitoring facilities and prioritizing work orders."""

    def __init__(self):
        pass

    # Safety keywords that force URGENT regardless of a (possibly missing or
    # mislabeled) severity field. A work order with no severity should never be
    # quietly triaged to MEDIUM when its title says "gas leak".
    _SAFETY_KEYWORDS = ("gas leak", "fire", "smoke", "flood", "electrical", "shock",
                        "carbon monoxide", "asbestos", "collapse", "no power", "burst")
    _URGENT_SEVERITIES = ("CRITICAL", "HIGH", "URGENT", "SEV1", "SEV2", "P0", "P1", "EMERGENCY")

    async def prioritize_work_order(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """Calculates facility maintenance priorities from severity, keywords, and occupant impact."""
        title = (request_data.get("issue_title") or "")
        logger.info(f"FacilityAgent prioritizing work order: {title}")

        raw = request_data.get("severity")
        severity = str(raw).upper() if raw is not None else "UNKNOWN"
        title_l = title.lower()

        safety = any(k in title_l for k in self._SAFETY_KEYWORDS)
        if safety or severity in self._URGENT_SEVERITIES:
            priority, hours = "URGENT", 2
        elif severity in ("MEDIUM", "MODERATE", "SEV3", "P2"):
            priority, hours = "MEDIUM", 8
        elif severity in ("LOW", "SEV4", "P3", "P4"):
            priority, hours = "LOW", 24
        else:
            # Unknown/unrecognized severity is NOT assumed low — route to a human
            # to classify rather than silently defaulting a possibly-critical order.
            priority, hours = "NEEDS_TRIAGE", 4

        return {
            "issue_title": title,
            "assigned_team": "Maintenance Lead",
            "priority": priority,
            "scheduled_hours": hours,
            "safety_flagged": safety,
        }
