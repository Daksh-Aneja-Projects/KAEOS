"""
KAEOS — Workflow Spec Registry

Single place that aggregates every domain's declared WorkflowSpecs. Lives above
the domain packages (which import app.core.workflow) so there is no import
cycle. Both the Org Pulse SLA sweep and the automation engine resolve specs
through here instead of re-listing the seven SPECS dicts.
"""
from typing import Dict, List

from app.core.workflow import WorkflowSpec
from app.finance.services.workflows import SPECS as FINANCE_SPECS
from app.hr.services.workflows import SPECS as HR_SPECS
from app.sales.services.workflows import SPECS as SALES_SPECS
from app.support.services.workflows import SPECS as SUPPORT_SPECS
from app.operations.services.workflows import SPECS as OPERATIONS_SPECS
from app.legal.services.workflows import SPECS as LEGAL_SPECS
from app.engineering.services.workflows import SPECS as ENGINEERING_SPECS

_DOMAIN_SPEC_DICTS = (
    FINANCE_SPECS, HR_SPECS, SALES_SPECS, SUPPORT_SPECS,
    OPERATIONS_SPECS, LEGAL_SPECS, ENGINEERING_SPECS,
)

# entity_type -> WorkflowSpec (entity_type strings are globally unique).
SPECS_BY_ENTITY: Dict[str, WorkflowSpec] = {}
for _d in _DOMAIN_SPEC_DICTS:
    SPECS_BY_ENTITY.update(_d)

ALL_SPECS: List[WorkflowSpec] = list(SPECS_BY_ENTITY.values())


def get_spec(entity_type: str) -> WorkflowSpec | None:
    return SPECS_BY_ENTITY.get(entity_type)
