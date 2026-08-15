"""
KAEOS HR — Workflow Specs
State machines for time-off requests, job requisitions, candidate stages, and
the broader HR schema (benefits, onboarding/offboarding tasks, ER cases,
payroll, learning, workforce planning, timesheets, performance reviews).
"""
from app.core.workflow import WorkflowSpec, TransitionContext
from app.hr.models.recruiting import JobRequisition
from app.hr.models.time_attendance import TimeOffRequest, Timesheet
from app.hr.models.benefits import BenefitEnrollment
from app.hr.models.onboarding import BoardingTask
from app.hr.models.employee_relations import ERCase
from app.hr.models.payroll import PayrollRun
from app.hr.models.learning import CourseEnrollment
from app.hr.models.workforce_planning import HeadcountPlan
from app.hr.models.performance import PerformanceReview


def _timeoff_approved(req: TimeOffRequest, ctx: TransitionContext) -> None:
    req.ai_auto_approved = False  # a human transition always overrides auto-approval
    if ctx.note:
        req.ai_decision_reason = ctx.note[:256]


TIME_OFF_WORKFLOW = WorkflowSpec(
    domain="hr",
    entity_type="time_off_request",
    model=TimeOffRequest,
    transitions={
        "REQUESTED": ["APPROVED", "DENIED", "CANCELLED"],
        "APPROVED": ["CANCELLED"],
        "DENIED": ["REQUESTED"],
    },
    on_enter={"APPROVED": _timeoff_approved},
    sla_hours={"REQUESTED": 48},
)

REQUISITION_WORKFLOW = WorkflowSpec(
    domain="hr",
    entity_type="job_requisition",
    model=JobRequisition,
    transitions={
        "DRAFT": ["PENDING_APPROVAL", "CANCELLED"],
        "PENDING_APPROVAL": ["OPEN", "DRAFT", "CANCELLED"],
        "OPEN": ["ON_HOLD", "FILLED", "CANCELLED"],
        "ON_HOLD": ["OPEN", "CANCELLED"],
    },
    sla_hours={"PENDING_APPROVAL": 120},
)

# NOTE: candidate stage advancement intentionally has NO WorkflowSpec here —
# POST /hr/candidates/{id}/advance (gated, with screening provenance) is the
# single sanctioned path; a second engine-driven path would fork the funnel.

BENEFIT_ENROLLMENT_WORKFLOW = WorkflowSpec(
    domain="hr",
    entity_type="benefit_enrollment",
    model=BenefitEnrollment,
    transitions={
        "PENDING": ["ACTIVE", "WAIVED"],
        "ACTIVE": ["TERMINATED"],
    },
    sla_hours={"PENDING": 168},  # open-enrollment window before it's stale
)

BOARDING_TASK_WORKFLOW = WorkflowSpec(
    domain="hr",
    entity_type="boarding_task",
    model=BoardingTask,
    transitions={
        "PENDING": ["IN_PROGRESS", "SKIPPED"],
        "IN_PROGRESS": ["COMPLETED", "SKIPPED"],
    },
    sla_hours={"PENDING": 72},
)

ER_CASE_WORKFLOW = WorkflowSpec(
    domain="hr",
    entity_type="er_case",
    model=ERCase,
    transitions={
        "OPEN": ["UNDER_INVESTIGATION", "PENDING_ACTION", "CLOSED"],
        "UNDER_INVESTIGATION": ["PENDING_ACTION", "RESOLVED"],
        "PENDING_ACTION": ["RESOLVED"],
        "RESOLVED": ["CLOSED"],
    },
    sla_hours={"OPEN": 72, "UNDER_INVESTIGATION": 240},
)

PAYROLL_RUN_WORKFLOW = WorkflowSpec(
    domain="hr",
    entity_type="payroll_run",
    model=PayrollRun,
    transitions={
        "PREP": ["PROCESSING", "FAILED"],
        "PROCESSING": ["PENDING_APPROVAL", "FAILED"],
        "PENDING_APPROVAL": ["COMPLETED", "PROCESSING"],
    },
    sla_hours={"PENDING_APPROVAL": 48},
)

COURSE_ENROLLMENT_WORKFLOW = WorkflowSpec(
    domain="hr",
    entity_type="course_enrollment",
    model=CourseEnrollment,
    transitions={
        "ENROLLED": ["IN_PROGRESS", "EXPIRED"],
        "IN_PROGRESS": ["COMPLETED", "EXPIRED"],
    },
)

HEADCOUNT_PLAN_WORKFLOW = WorkflowSpec(
    domain="hr",
    entity_type="headcount_plan",
    model=HeadcountPlan,
    transitions={
        "DRAFT": ["ACTIVE", "ARCHIVED"],
        "ACTIVE": ["ARCHIVED"],
    },
)

TIMESHEET_WORKFLOW = WorkflowSpec(
    domain="hr",
    entity_type="timesheet",
    model=Timesheet,
    transitions={
        "DRAFT": ["SUBMITTED"],
        "SUBMITTED": ["APPROVED", "DRAFT"],
        "APPROVED": ["PROCESSED"],
    },
    sla_hours={"SUBMITTED": 72},
)

# A review's forward path is normally driven by the payload-carrying
# self-rating/manager-rating endpoints (they stamp status alongside the
# submitted assessment, which a bare transition can't express). The generic
# engine only owns kicking a DRAFT review off — everything past that goes
# through the rating endpoints so a rating can never be skipped.
PERFORMANCE_REVIEW_WORKFLOW = WorkflowSpec(
    domain="hr",
    entity_type="performance_review",
    model=PerformanceReview,
    transitions={
        "DRAFT": ["PENDING_EMPLOYEE"],
    },
)

SPECS = {
    "time_off_request": TIME_OFF_WORKFLOW,
    "job_requisition": REQUISITION_WORKFLOW,
    "benefit_enrollment": BENEFIT_ENROLLMENT_WORKFLOW,
    "boarding_task": BOARDING_TASK_WORKFLOW,
    "er_case": ER_CASE_WORKFLOW,
    "payroll_run": PAYROLL_RUN_WORKFLOW,
    "course_enrollment": COURSE_ENROLLMENT_WORKFLOW,
    "headcount_plan": HEADCOUNT_PLAN_WORKFLOW,
    "timesheet": TIMESHEET_WORKFLOW,
    "performance_review": PERFORMANCE_REVIEW_WORKFLOW,
}
