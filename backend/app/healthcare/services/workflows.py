"""
KAEOS Healthcare — Workflow Specs

Declarative state machines for clinical encounters and clinical tasks; every
status transition flows through app.core.workflow.apply_transition instead of
a raw field assignment (mirrors app/finance/services/workflows.py). SLA hours
mirror the pack's process_definitions (app/workforce/domain_packs/packs/
healthcare.yaml): triage in 2h, coding/prior-auth work in 8h.
"""
from app.core.workflow import WorkflowSpec
from app.healthcare.models.core import ClinicalTask, PatientEncounter
from app.models.execution_status import ExecutionStatus

# OPEN -> TRIAGED -> CODED -> CLOSED, matching PatientEncounter.status's
# documented enum (models/core.py). A CLOSED encounter never reopens through
# this state machine; a real correction is a new encounter.
ENCOUNTER_WORKFLOW = WorkflowSpec(
    domain="healthcare",
    entity_type="encounter",
    model=PatientEncounter,
    transitions={
        "OPEN": ["TRIAGED", "CLOSED"],
        "TRIAGED": ["CODED", "CLOSED"],
        "CODED": ["CLOSED"],
    },
    # encounter_triage's pack SLA is 2h (time to first triage); coding_suggestion
    # is 8h (time to move a triaged encounter to coded).
    sla_hours={"OPEN": 2, "TRIAGED": 8},
)

# OPEN -> IN_PROGRESS -> {PENDING_HITL, DONE, BLOCKED}, matching
# ClinicalTask.status's documented enum. BLOCKED can resume to IN_PROGRESS (a
# cleared blocker, e.g. a Part 2 consent that lands) or fall back to OPEN.
CLINICAL_TASK_WORKFLOW = WorkflowSpec(
    domain="healthcare",
    entity_type="clinical_task",
    model=ClinicalTask,
    transitions={
        "OPEN": ["IN_PROGRESS", "BLOCKED"],
        "IN_PROGRESS": [ExecutionStatus.PENDING_HITL, "DONE", "BLOCKED"],
        ExecutionStatus.PENDING_HITL: ["DONE", "BLOCKED", "IN_PROGRESS"],
        "BLOCKED": ["IN_PROGRESS", "OPEN"],
    },
    # coding_suggestion and prior_auth_prep both declare an 8h SLA; PENDING_HITL
    # gets a tighter 4h floor (matches phi_disclosure_review's human-turnaround
    # expectation) since a task waiting on a human reviewer should not linger.
    sla_hours={"OPEN": 2, "IN_PROGRESS": 8, ExecutionStatus.PENDING_HITL: 4},
)

SPECS = {"encounter": ENCOUNTER_WORKFLOW, "clinical_task": CLINICAL_TASK_WORKFLOW}
