import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

# Maps Workday business-process / event-type strings to KAEOS canonical event
# types. Extend this as additional Workday processes are onboarded — the parser
# classifies from the payload rather than assuming a single event type.
_WORKDAY_EVENT_TYPE_MAP = {
    "termination": "EMPLOYEE_TERMINATION",
    "terminate_employee": "EMPLOYEE_TERMINATION",
    "voluntary_termination": "EMPLOYEE_TERMINATION",
    "involuntary_termination": "EMPLOYEE_TERMINATION",
    "hire": "EMPLOYEE_HIRE",
    "hire_employee": "EMPLOYEE_HIRE",
    "job_change": "EMPLOYEE_JOB_CHANGE",
    "transfer": "EMPLOYEE_JOB_CHANGE",
    "promotion": "EMPLOYEE_JOB_CHANGE",
}


class WorkdayEventParser:
    def parse(self, raw_payload: Dict[str, Any]) -> Dict[str, Any]:
        logger.info("WorkdayEventParser: Transforming raw Workday payload to canonical event.")

        # Classify the event from the payload's declared type instead of assuming
        # a single event kind. Workday spreads this across a few field names.
        raw_type = (
            raw_payload.get("event_type")
            or raw_payload.get("business_process_type")
            or raw_payload.get("businessProcessType")
            or raw_payload.get("transaction_type")
        )
        if not raw_type:
            raise ValueError(
                "Workday payload is missing an event/business-process type; "
                "cannot classify the event."
            )

        canonical_type = _WORKDAY_EVENT_TYPE_MAP.get(str(raw_type).strip().lower())
        if not canonical_type:
            raise ValueError(f"Unsupported Workday event type: {raw_type!r}")

        canonical: Dict[str, Any] = {
            "canonical_event_type": canonical_type,
            "employee_id": raw_payload.get("worker_id") or raw_payload.get("employee_id"),
            "department": raw_payload.get("department", "Unknown"),
            "manager": raw_payload.get("manager_id"),
            "role": raw_payload.get("role", "Employee"),
        }

        # Every event must identify the worker it concerns.
        if not canonical["employee_id"]:
            raise ValueError("Missing required canonical field: employee_id")

        # Event-type-specific fields — only populated (and required) for the
        # events that actually carry them.
        if canonical_type == "EMPLOYEE_TERMINATION":
            canonical["termination_date"] = raw_payload.get("termination_date")
            if not canonical["termination_date"]:
                raise ValueError("Missing required canonical field: termination_date")
        elif canonical_type == "EMPLOYEE_HIRE":
            canonical["hire_date"] = raw_payload.get("hire_date")
            if not canonical["hire_date"]:
                raise ValueError("Missing required canonical field: hire_date")
        elif canonical_type == "EMPLOYEE_JOB_CHANGE":
            canonical["effective_date"] = raw_payload.get("effective_date")
            canonical["new_role"] = raw_payload.get("new_role")

        return canonical
