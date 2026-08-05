"""KAEOS — Controls evidence & audit-readiness inventory.

Independent certification (SOC 2, ISO 27001, HIPAA) is a third-party AUDIT, not
something software can grant itself. What software CAN do is make the technical
controls those audits look for real, and produce the evidence an auditor needs.

This module is that evidence: a hand-audited inventory of the security/privacy
controls KAEOS actually implements, each mapped to the relevant framework
criteria and pointing at the code and tests that prove it. Controls that are
genuinely EXTERNAL (the attestation itself, an independent pen-test, load
testing) are listed and marked as such - never claimed as satisfied - so the
report stays honest and usable in a real audit.
"""
from __future__ import annotations

from dataclasses import dataclass, field


class ControlStatus:
    IMPLEMENTED = "implemented"      # built and regression-tested in this repo
    OPERATIONAL = "operational"     # a deploy-time configuration the operator owns
    EXTERNAL = "external"           # a third-party action software cannot self-grant


@dataclass(frozen=True)
class Control:
    id: str
    name: str
    status: str
    description: str
    frameworks: dict = field(default_factory=dict)   # {"SOC2": [...], "ISO27001": [...], ...}
    evidence: tuple = ()                              # code/test paths that prove it


# ── The inventory. Every IMPLEMENTED entry names the file/test that proves it. ──
_CONTROLS: list[Control] = [
    Control(
        "AC-1", "Per-tenant isolation (row-level security)", ControlStatus.IMPLEMENTED,
        "Every tenant table is under Postgres RLS; the app role cannot read or "
        "write across tenants. Verified against a live Postgres.",
        {"SOC2": ["CC6.1"], "ISO27001": ["A.9.4.1", "A.13.1.3"], "GDPR": ["Art.32"]},
        ("app/core/rls.py", "scripts/verify_rls.py", "tests/e2e/test_28_cross_tenant_denial.py"),
    ),
    Control(
        "AC-2", "Default-deny RBAC on every mutation", ControlStatus.IMPLEMENTED,
        "Every state-changing endpoint carries a role/service/admin gate or a "
        "reviewed allowlist; a lint fails the build if a new ungated mutation appears.",
        {"SOC2": ["CC6.1", "CC6.3"], "ISO27001": ["A.9.4.1"]},
        ("app/core/tenant.py", "tests/test_default_deny.py", "tests/test_rbac_coverage.py"),
    ),
    Control(
        "AC-3", "Authentication + MFA", ControlStatus.IMPLEMENTED,
        "JWT bearer auth with lockout on repeated failures; optional TOTP MFA "
        "self-service; SSO (OIDC).",
        {"SOC2": ["CC6.1"], "ISO27001": ["A.9.4.2"]},
        ("app/services/auth.py", "app/api/routes/sso.py"),
    ),
    Control(
        "CR-1", "Secrets encrypted at rest (Fernet)", ControlStatus.IMPLEMENTED,
        "Connector and model credentials are Fernet-encrypted at rest and never "
        "serialized back out of the API.",
        {"SOC2": ["CC6.7"], "ISO27001": ["A.10.1.1"], "PCI": ["3.4"]},
        ("app/services/live_connectors.py", "app/models/settings.py"),
    ),
    Control(
        "AU-1", "Security audit logging", ControlStatus.IMPLEMENTED,
        "Auth successes/failures, RBAC denials, HITL decisions, config changes and "
        "export actions are logged (best-effort, non-blocking) across ~30 modules.",
        {"SOC2": ["CC7.2"], "ISO27001": ["A.12.4.1"], "SOX": ["404"]},
        ("app/core/audit.py",),
    ),
    Control(
        "AU-2", "Hash-chained decision provenance", ControlStatus.IMPLEMENTED,
        "Every AI decision is written to a tamper-evident, hash-chained provenance "
        "ledger with full lineage.",
        {"SOC2": ["CC7.3"], "SOX": ["302", "404"]},
        ("app/services/quantum_ledger.py", "app/services/actuation/actuator.py",
         "tests/e2e/test_23_coverage_gaps.py"),
    ),
    Control(
        "PR-1", "Right-to-erasure (subject + tenant)", ControlStatus.IMPLEMENTED,
        "Erasure tombstones PII, deletes stored blobs, purges vector embeddings, "
        "and is journaled so a restored backup cannot resurrect the subject.",
        {"GDPR": ["Art.17", "Art.28"], "CCPA": ["1798.105"], "SOC2": ["P4"]},
        ("app/services/privacy_erasure.py", "app/core/polystore/blob_store.py",
         "tests/test_erasure_blob_and_journal.py"),
    ),
    Control(
        "PR-2", "Storage-limitation retention windows", ControlStatus.IMPLEMENTED,
        "Opt-in, per-class retention windows hard-delete transient telemetry past "
        "its window; the allow-list structurally excludes the integrity ledger.",
        {"GDPR": ["Art.5(1)(e)"], "ISO27001": ["A.18.1.3"]},
        ("app/services/retention.py", "tests/test_retention_and_erasure.py"),
    ),
    Control(
        "PR-3", "Pre-egress PII scrub + data residency", ControlStatus.IMPLEMENTED,
        "PII is scrubbed before any cloud LLM call; local-LLM-only mode keeps all "
        "inference in-region.",
        {"GDPR": ["Art.32", "Art.44"], "HIPAA": ["164.312(e)"]},
        ("app/transforms/pii_scrubber.py", "app/services/llm_router.py"),
    ),
    Control(
        "PR-4", "Prompt-injection screening of untrusted content", ControlStatus.IMPLEMENTED,
        "Ingested/connected content is scanned for injection patterns and matched "
        "command spans are neutralized before entering an LLM context (defense in "
        "depth, layered with source-authority weighting and the HITL gates).",
        {"SOC2": ["CC6.8"], "ISO27001": ["A.14.2.5"]},
        ("app/services/prompt_guard.py", "tests/test_prompt_guard.py"),
    ),
    Control(
        "OP-1", "Human-in-the-loop gates for high-consequence actions", ControlStatus.IMPLEMENTED,
        "Low-confidence and high-consequence action classes route to a blocking, "
        "attributable human approval before execution.",
        {"SOC2": ["CC7.4"], "SOX": ["404"], "ISO27001": ["A.12.1.2"]},
        ("app/agents/runtime.py", "app/api/routes/hitl.py"),
    ),
    Control(
        "OP-2", "Rate limiting", ControlStatus.IMPLEMENTED,
        "Per-tenant limiter, Redis-backed and shared across replicas when Redis is "
        "reachable.",
        {"SOC2": ["CC6.6"], "ISO27001": ["A.13.1.1"]},
        ("app/core/middleware.py", "tests/test_middleware_limits.py"),
    ),
    Control(
        "OP-3", "High-availability background jobs (leader election)", ControlStatus.IMPLEMENTED,
        "Singleton loops elect one leader (Redis -> Postgres advisory -> local) so "
        "every replica boots identically and only one runs them.",
        {"SOC2": ["A1.1"], "ISO27001": ["A.17.2.1"]},
        ("app/services/leader_lock.py", "tests/test_leader_lock.py"),
    ),
    Control(
        "OP-4", "Backup + restore with deletion replay", ControlStatus.IMPLEMENTED,
        "Backup/restore scripts plus a deletion journal whose replay re-applies "
        "erasures after a restore (so backups cannot resurrect deleted PII).",
        {"SOC2": ["A1.2"], "ISO27001": ["A.12.3.1"], "GDPR": ["Art.17"]},
        ("scripts/", "app/services/privacy_erasure.py"),
    ),
    # ── Genuinely external — listed, never claimed satisfied. ─────────────────
    Control(
        "EX-1", "Independent SOC 2 / ISO 27001 / HIPAA attestation", ControlStatus.EXTERNAL,
        "A third-party audit firm must examine and attest the controls. Software "
        "cannot self-certify; this report is the evidence you take INTO that audit.",
        {"SOC2": ["attestation"], "ISO27001": ["certification"], "HIPAA": ["attestation"]},
        (),
    ),
    Control(
        "EX-2", "Independent penetration test", ControlStatus.EXTERNAL,
        "An external security firm should pen-test the deployment before processing "
        "regulated data.",
        {"SOC2": ["CC4.1"], "ISO27001": ["A.12.6.1"]},
        (),
    ),
    Control(
        "EX-3", "Load / soak testing at target concurrency", ControlStatus.OPERATIONAL,
        "Run before go-live at your expected concurrency; a deploy-time exercise the "
        "operator owns.",
        {"SOC2": ["A1.1"]},
        (),
    ),
]


def _control_dict(c: Control) -> dict:
    return {
        "id": c.id, "name": c.name, "status": c.status,
        "description": c.description, "frameworks": c.frameworks,
        "evidence": list(c.evidence),
    }


def framework_coverage() -> dict:
    """Per-framework: which implemented controls map to it (auditor cross-ref)."""
    coverage: dict[str, list[str]] = {}
    for c in _CONTROLS:
        if c.status != ControlStatus.IMPLEMENTED:
            continue
        for fw in c.frameworks:
            coverage.setdefault(fw, []).append(c.id)
    return coverage


def build_controls_report() -> dict:
    """The audit-readiness evidence report. Deterministic and side-effect free."""
    implemented = [c for c in _CONTROLS if c.status == ControlStatus.IMPLEMENTED]
    external = [c for c in _CONTROLS if c.status == ControlStatus.EXTERNAL]
    operational = [c for c in _CONTROLS if c.status == ControlStatus.OPERATIONAL]
    return {
        "summary": {
            "total": len(_CONTROLS),
            "implemented": len(implemented),
            "operational": len(operational),
            "external": len(external),
        },
        "framework_coverage": framework_coverage(),
        "controls": [_control_dict(c) for c in _CONTROLS],
        "honest_note": (
            "This is audit-readiness evidence, NOT a certificate. The technical "
            "controls are implemented and tested; independent attestation (EX-1) "
            "and an external penetration test (EX-2) are third-party actions that "
            "software cannot self-grant. Validate against your own obligations."
        ),
    }
