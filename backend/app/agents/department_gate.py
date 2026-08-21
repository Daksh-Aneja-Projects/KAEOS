"""
KAEOS — Department Gate: the single gated-skill runner for every department.

Before this module, each of the ten department packages carried its own
``agents/gated_runner.py``: ~100 lines of the same code, ten times over. The
copies were never quite the same, and the differences were not design — they
were drift. Four examples found in the tree:

  * ``extract_decision`` existed in ten copies that had diverged into five
    textually different (but semantically identical) variants;
  * the Gate-6 lawful-basis fix ("derive the flag from a real ``legal_basis``,
    never assert it") reached hr, sales, support and healthcare but had missed
    ``legal`` — the department whose entire remit is GDPR/CCPA — which used to
    set ``data_processing_basis_logged = True`` unconditionally (now fixed: it
    derives the flag like the rest, and every legal agent supplies a real basis);
  * hr and healthcare distinguished ``compliance_tags=[]`` ("deliberately no
    tags") from ``None`` ("use the default") while the other eight silently
    replaced an explicit empty list with their defaults (now uniform: only
    ``None`` means defaults, in every department);
  * ``financial_amount_logged`` is gated on ``SOX`` in hr/sales but on
    ``SOX or GAAP`` in finance.

Consolidating removes the *mechanism* from ten files while keeping each
department's *policy* declarative and visible in one table. Every behavioural
quirk above is preserved exactly as it is today — including the ones that look
like bugs. Where a quirk is suspicious, it is marked ``REVIEW:`` in the
department's config so it is a deliberate decision rather than a buried
accident. Changing them is a behavioural change and belongs in its own commit.

Adding a department is now a ``DepartmentGate(...)`` entry plus a three-line
shim, not another 100-line copy.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from app.agents.runtime import AgentExecutor
from app.models.domain import Skill
from app.services.compliance import ComplianceEngine
from app.services.hitl_manager import hitl_manager

logger = logging.getLogger(__name__)

__all__ = ["AuditFlag", "DepartmentGate", "extract_decision"]


@dataclass(frozen=True)
class AuditFlag:
    """One Gate-6 audit flag seeded into the execution context.

    Gate 6 asks whether an execution logged the artifacts its compliance regime
    demands. Seeding a flag as a bare ``True`` answers that question with an
    assertion instead of a fact, which is precisely what the flag is supposed to
    rule out. So the default here is to *derive* the flag from a real context
    key: present and truthy means the artifact was actually supplied.

    Attributes:
        flag:    context key written into the execution context.
        tags:    seed the flag only when one of these compliance tags is
                 attached to the skill. Empty means "always seed".
        source:  context key whose truthiness becomes the flag's value.
                 ``None`` seeds a literal ``True`` — an assertion, not a fact.
                 Only ``legal`` still does this; see ``LEGAL`` below.
        force:   ``True`` overwrites a caller-supplied value; the default
                 ``False`` uses ``setdefault`` so an explicit caller value wins.
    """

    flag: str
    tags: Sequence[str] = ()
    source: Optional[str] = None
    force: bool = False

    def applies_to(self, compliance_tags: Sequence[str]) -> bool:
        return not self.tags or any(t in compliance_tags for t in self.tags)

    def value_from(self, context: Mapping[str, Any]) -> Any:
        return True if self.source is None else bool(context.get(self.source))

    def seed(self, ctx: Dict[str, Any], context: Mapping[str, Any],
             compliance_tags: Sequence[str]) -> None:
        if not self.applies_to(compliance_tags):
            return
        if self.force:
            ctx[self.flag] = self.value_from(context)
        else:
            ctx.setdefault(self.flag, self.value_from(context))


@dataclass(frozen=True)
class DepartmentGate:
    """A department's gate policy: the only thing that differs between the ten.

    The runner mechanism lives in :meth:`run`; everything a department is
    allowed to vary is a field here, so a reviewer can diff ten policies in one
    screen instead of reading ten near-identical modules.

    Attributes:
        domain:              department name, used for ``department``/``domain``.
        default_compliance:  tags applied when the caller passes none.
        default_confidence:  confidence for the synthetic skill.
        confidence_overrides: per-skill confidence, applied before the skill is
                              built. Used to force specific skills to HITL.
                              Applied even when the caller passed a confidence.
        compliance_overrides: per-skill default tags for skills that carry a
                              heavier control set than the department default
                              (engineering's production deploys). Applied only
                              when the caller supplied no tags of their own.
        audit_flags:         Gate-6 flags to seed (see :class:`AuditFlag`).
        always_hitl:         when set, written to the skill dict so Gate 3
                             cannot de-escalate below a human.
    """

    domain: str
    default_compliance: Sequence[str]
    default_confidence: float = 0.85
    confidence_overrides: Mapping[str, float] = field(default_factory=dict)
    compliance_overrides: Mapping[str, Sequence[str]] = field(default_factory=dict)
    audit_flags: Sequence[AuditFlag] = ()
    always_hitl: Optional[bool] = None

    def resolve_tags(
        self, compliance_tags: Optional[List[str]], skill_id: str = "",
    ) -> List[str]:
        """Apply empty-tag semantics and per-skill defaults, uniformly (S4.3).

        Only ``None`` means "use the department default"; ``[]`` means
        "deliberately no compliance tags" everywhere — the hr fairness sweep
        relies on this (its EEOC check IS the fairness gate). Departments used to
        disagree: three distinguished ``[]`` from ``None`` while seven silently
        turned ``[]`` back into the defaults (truthiness). Standardised on ``is
        None`` so the same argument means the same thing in every department.

        A ``compliance_overrides`` entry replaces the department default for one
        skill, and only when the caller supplied no tags: an explicit argument
        always wins over a per-skill default.
        """
        default = list(self.compliance_overrides.get(skill_id, self.default_compliance))
        return default if compliance_tags is None else compliance_tags

    async def run(
        self,
        skill_id: str,
        steps: List[Dict[str, Any]],
        context: Dict[str, Any],
        tenant_id: str,
        *,
        compliance_tags: Optional[List[str]] = None,
        confidence: Optional[float] = None,
        extra_context: Optional[Mapping[str, Any]] = None,
        extra_skill_fields: Optional[Mapping[str, Any]] = None,
        domain: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Route a department action through the full 7-gate ``AgentExecutor``.

        Builds the synthetic (non-persisted) ``Skill`` the fairness and debate
        gates need, seeds the department's Gate-6 audit flags, and hands off to
        the executor. Returns the executor result dict; on ``SUCCESS_CLEAN`` it
        carries ``reasoning_chain`` for :func:`extract_decision`.

        Args:
            extra_context:      department-specific context keys (hr's
                                ``requires_fairness_assessment``, finance's
                                four-eyes ``maker``/``approver``). Applied
                                before audit flags so a department can supply a
                                flag's source key.
            extra_skill_fields: extra keys for the skill dict.
            domain:             overrides the configured domain for callers that
                                pass one explicitly.
        """
        domain = domain or self.domain
        tags = self.resolve_tags(compliance_tags, skill_id)
        confidence = self.default_confidence if confidence is None else confidence
        confidence = self.confidence_overrides.get(skill_id, confidence)
        execution_id = context.get("execution_id") or str(uuid.uuid4())

        skill_dict: Dict[str, Any] = {
            "skill_id": skill_id,
            "department": domain,
            "steps": steps,
            "compliance_tags": tags,
            "confidence": confidence,
        }
        if self.always_hitl is not None:
            skill_dict["always_hitl"] = self.always_hitl
        if extra_skill_fields:
            skill_dict.update(extra_skill_fields)

        # Synthetic, non-persisted Skill so the fairness + debate gates engage.
        skill_obj = Skill(
            skill_id=skill_id,
            department=domain,
            domain=domain,
            compliance_tags=tags,
            confidence=confidence,
            confidence_tier="INFERRED",
            execution_count=0,
            success_rate=0.0,
            steps=steps,
        )

        ctx: Dict[str, Any] = {
            **context,
            "tenant_id": tenant_id,
            "execution_id": execution_id,
            "_skill_obj": skill_obj,
        }
        if extra_context:
            ctx.update(extra_context)

        for audit_flag in self.audit_flags:
            audit_flag.seed(ctx, context, tags)

        executor = AgentExecutor(ComplianceEngine(), hitl_manager)
        return await executor.execute_skill(skill_dict, ctx)


def extract_decision(result: Dict[str, Any]) -> Dict[str, Any]:
    """Best-effort parse of the primary step's JSON decision from a gated result.

    Looks at the last step in ``reasoning_chain`` and parses embedded JSON.
    Returns ``{}`` when nothing parseable is present — a model that failed to
    emit JSON must not take down a governed decision that already passed its
    gates, but the miss is logged rather than swallowed.

    This replaces ten per-department copies that had drifted into five textual
    variants with no behavioural difference between them.
    """
    from app.services.json_utils import extract_json_object

    chain = result.get("reasoning_chain") or []
    if not chain:
        return {}
    decision_text = chain[-1].get("decision", "") or ""
    try:
        return extract_json_object(decision_text)
    except ValueError as e:
        logger.warning("extract_decision: could not parse JSON decision: %s", e)
        return {}


# ── Department policies ──────────────────────────────────────────────────────
# One table replacing ten modules. Every value below reproduces the behaviour
# the corresponding gated_runner.py has today; `REVIEW:` marks a quirk that is
# preserved deliberately and is worth a decision, not a silent inheritance.

# Production deploys are treated like customer-facing support responses: they
# always require human approval, because an autonomous agent shipping to
# production is precisely the failure mode enterprises fear.
_ENGINEERING_DEPLOY_SKILL = "engineering_deploy_approval"
# The full change-management control set: SOC2 CC8.1 (peer review + change record
# + CI), ISO 27001 change control (rollback + approval), and change-freeze
# enforcement. These have deterministic checkers in
# app/compliance/checkers/engineering.py.
DEPLOY_COMPLIANCE = ("SOC2", "ISO27001", "CHANGE_FREEZE")

ENGINEERING = DepartmentGate(
    domain="engineering",
    default_compliance=("SOC2", "CHANGE_MANAGEMENT"),
    compliance_overrides={_ENGINEERING_DEPLOY_SKILL: DEPLOY_COMPLIANCE},
    # Below the 0.82 HITL threshold on purpose: skills that mutate production
    # route to a human regardless of the model's confidence.
    confidence_overrides={_ENGINEERING_DEPLOY_SKILL: 0.79},
)

FINANCE = DepartmentGate(
    domain="finance",
    default_compliance=("SOX", "GAAP", "PCI"),
    audit_flags=(
        # GAAP-inclusive is the standard: a financial amount under GAAP must be
        # logged just as one under SOX must (hr and sales now match this).
        AuditFlag("financial_amount_logged", ("SOX", "GAAP"), source="amount"),
        AuditFlag("pci_dss_compliant", ("PCI",), source="pci_validated"),
    ),
)

HEALTHCARE = DepartmentGate(
    domain="healthcare",
    default_compliance=("HIPAA_MINIMUM_NECESSARY", "HIPAA_AUTHORIZATION", "PART2"),
    default_confidence=0.95,  # the pack's confidence floor
    always_hitl=True,         # a clinical action never de-escalates below a human
    # Unconditional by design: every healthcare action is a HIPAA disclosure, so
    # the flag is seeded regardless of which tags are attached — but its value is
    # still derived from a real lawful basis rather than asserted.
    audit_flags=(AuditFlag("data_processing_basis_logged", source="legal_basis"),),
)

HR = DepartmentGate(
    domain="hr",
    default_compliance=("EEOC", "GDPR"),
    audit_flags=(
        AuditFlag("data_processing_basis_logged", ("GDPR", "HIPAA", "CCPA"), source="legal_basis"),
        AuditFlag("financial_amount_logged", ("SOX", "GAAP"), source="amount"),
    ),
)

LEGAL = DepartmentGate(
    domain="legal",
    default_compliance=("GDPR", "CCPA", "PRIVACY"),
    audit_flags=(
        # Derived from a real `legal_basis`, exactly like hr/sales/support/
        # healthcare. This department IS GDPR/CCPA, so it was the one that most
        # needed to PROVE a lawful basis rather than assert one — yet the old
        # duplicated code hardcoded it (source=None, force=True), leaving legal
        # structurally unable to fail its own Gate-6 lawful-basis audit. Now Gate
        # 6 fails a legal run that supplies no basis, and every legal agent
        # supplies a genuine one (see app/legal/agents/*_agent.py).
        AuditFlag("data_processing_basis_logged", ("GDPR", "CCPA"), source="legal_basis"),
    ),
)

LENDING = DepartmentGate(
    domain="lending",
    default_compliance=("ECOA", "FAIR_LENDING", "TILA"),
    default_confidence=0.9,
    # H18: credit denial and fair-lending are high-consequence — bring lending to
    # healthcare-grade. A credit decision routes to a human (below the 0.82
    # autonomy floor); the loan amount and the fair-lending basis are both proven
    # in the Gate-6 audit trail (derived from a real amount / legal_basis, like
    # finance/healthcare — never asserted).
    confidence_overrides={"lending_underwrite": 0.79},
    audit_flags=(
        AuditFlag("financial_amount_logged", ("TILA",), source="amount"),
        AuditFlag("data_processing_basis_logged", ("ECOA", "FAIR_LENDING"), source="legal_basis"),
    ),
)

OPERATIONS = DepartmentGate(
    domain="operations",
    default_compliance=("SOC2", "INTERNAL_CONTROL"),
)

PROCUREMENT = DepartmentGate(
    domain="procurement",
    default_compliance=(
        "THREE_WAY_MATCH", "SEGREGATION_OF_DUTIES",
        "SPEND_AUTHORIZATION", "OFAC_SANCTIONS",
    ),
    # H18: spend authority is high-consequence — bring procurement to healthcare-
    # grade. A PO-approval/award decision routes to a human (below the 0.82
    # autonomy floor), and the spend amount is proven in the Gate-6 audit trail.
    confidence_overrides={"procurement_spend_guard": 0.79},
    audit_flags=(
        AuditFlag("financial_amount_logged", ("SPEND_AUTHORIZATION",), source="amount"),
    ),
)

SALES = DepartmentGate(
    domain="sales",
    # Sales analytics processes customer data -> GDPR, not SOX. SOX's hard
    # human-approver blocker is for financial controls; tagging it here blocked
    # every sales agent unconditionally. Money-touching skills pass SOX
    # explicitly via compliance_tags.
    default_compliance=("GDPR",),
    confidence_overrides={"sales_proposal_gen": 0.50},  # force HITL: customer-facing
    audit_flags=(
        AuditFlag("data_processing_basis_logged", ("GDPR", "HIPAA", "CCPA"), source="legal_basis"),
        AuditFlag("financial_amount_logged", ("SOX", "GAAP"), source="amount"),
    ),
)

SUPPORT = DepartmentGate(
    domain="support",
    default_compliance=("GDPR", "CCPA", "SLA_BREACH", "PII_REDACTION"),
    # Force HITL on everything that drafts customer-facing reply text. The
    # resolution skill previously bypassed the gate entirely and closed
    # tickets on the model's own confidence claim.
    confidence_overrides={"support_auto_resolve": 0.79,
                          "support_ticket_resolution": 0.79},
    audit_flags=(
        AuditFlag("data_processing_basis_logged", ("GDPR", "HIPAA", "CCPA"), source="legal_basis"),
    ),
)


if __name__ == "__main__":
    # Self-check for the policy table: these are the governance behaviours the
    # ten former copies encoded, asserted against the one table that replaced
    # them. Run: python -m app.agents.department_gate
    _tags = ["GDPR"]

    # Derived flags stay false without a real lawful basis, and true with one.
    _ctx: Dict[str, Any] = {}
    for f in HR.audit_flags:
        f.seed(_ctx, {}, _tags)
    assert _ctx["data_processing_basis_logged"] is False, "no legal_basis must not assert one"
    _ctx = {}
    for f in HR.audit_flags:
        f.seed(_ctx, {"legal_basis": "contract"}, _tags)
    assert _ctx["data_processing_basis_logged"] is True, "a real legal_basis must be honoured"

    # Legal now derives the lawful-basis flag from a real `legal_basis`, like
    # every other department: no basis -> False (Gate 6 fails the run), a real
    # basis -> True. Every legal agent supplies one.
    _ctx = {}
    for f in LEGAL.audit_flags:
        f.seed(_ctx, {}, ["GDPR"])
    assert _ctx["data_processing_basis_logged"] is False, "legal: no legal_basis must not assert one"
    _ctx = {}
    for f in LEGAL.audit_flags:
        f.seed(_ctx, {"legal_basis": "legal_obligation:dsar"}, ["GDPR"])
    assert _ctx["data_processing_basis_logged"] is True, "legal: a real legal_basis is honoured"

    # Empty-tag semantics differ by department, on purpose.
    assert HR.resolve_tags([]) == [], "explicit [] means no tags, uniformly"
    assert HEALTHCARE.resolve_tags([]) == [], "explicit [] means no tags, uniformly"
    assert SALES.resolve_tags([]) == [], "sales too: [] now means no tags (S4.3)"
    assert SALES.resolve_tags(None) == ["GDPR"], "only None falls back to the default"
    assert HR.resolve_tags(None) == ["EEOC", "GDPR"], "None always means defaults"

    # Tag-scoped flags stay unseeded when the tag is absent.
    _ctx = {}
    for f in FINANCE.audit_flags:
        f.seed(_ctx, {"amount": 100}, ["GAAP"])
    assert _ctx == {"financial_amount_logged": True}, "PCI flag must not seed without the PCI tag"

    # Per-skill confidence overrides force HITL regardless of the caller's value.
    assert SALES.confidence_overrides["sales_proposal_gen"] == 0.50
    assert SUPPORT.confidence_overrides["support_auto_resolve"] == 0.79
    assert HEALTHCARE.always_hitl is True and HEALTHCARE.default_confidence == 0.95

    # A malformed model decision degrades to {} rather than raising.
    assert extract_decision({}) == {}
    assert extract_decision({"reasoning_chain": [{"decision": "not json"}]}) == {}
    assert extract_decision({"reasoning_chain": [{"decision": '{"ok": true}'}]}) == {"ok": True}

    print("department_gate policy self-check passed")
