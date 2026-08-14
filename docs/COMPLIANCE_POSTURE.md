# KAEOS Compliance Posture

Technical-control map for SOC 2, GDPR, and PII handling, plus the deterministic
statutory checkers that back the regulated verticals (healthcare/HIPAA,
lending/ECOA-TILA-FDCPA, procurement/SOX-OFAC). Every control listed here is
implemented and verifiable in this repository (file references given). This
document is the evidence map an auditor starts from.

Honest framing up front: a certificate (SOC 2 Type II, ISO 27001) is the
outcome of an organizational audit process - policies, personnel, and an
external auditor observing controls operating over time. Code delivers the
controls and the evidence; it cannot deliver the certificate. The gaps section
at the bottom says exactly what remains organizational.

## Control map

### Access control (SOC 2 CC6.1-CC6.3, GDPR Art. 32)

| Control | Implementation |
|---|---|
| Tenant isolation | PostgreSQL Row-Level Security on every tenant table; app connects as non-owner `kaeos_app` so RLS is enforced (migrations, `app/core/rls.py`; prod refuses SQLite: `app/core/database.py`) |
| Role-based access | viewer < operator < admin hierarchy enforced per-route (`require_role`, `app/core/tenant.py`); ADMIN/ANALYST/VIEWER user roles (`app/models/auth.py`) |
| Department-scoped access | `users.department` confines a user to one department's operational surface; enforced at router mounts + per-row (`require_department`, `check_department_scope`); the three regulated verticals (`/healthcare`, `/lending`, `/procurement`) are mounted behind that dependency in `app/main.py`, so PHI, credit files, and spend data are not reachable from an unrelated department's session; cross-domain aggregates deliberately readable (documented IP decision) |
| Platform-operator access | Cross-tenant fleet reads live only on `/api/v1/ops/*`, gated by the ADMIN_SECRET super-admin dependency (`require_superadmin`, `app/core/admin.py`) and served from the owner/maintenance session. A tenant JWT never authorizes a cross-tenant read. See [Security model](SECURITY_MODEL.md) |
| MFA | TOTP second factor (RFC 6238), secret Fernet-encrypted at rest (`app/models/mfa.py`, migration 0019) |
| SSO / provisioning | OIDC SSO, SAML, SCIM 2.0 provisioning (`app/api/routes/sso.py`, `scim.py`) |
| Service-to-service auth | `X-Service-Token` gate on internal mutations (`require_service_or_role`) |
| API keys | DB-backed, hashed at rest, revocable (`app/models/api_key.py`) |
| Access review evidence | `GET /auth/users/export.csv` - auditor-ready CSV of every account with role, department scope, status, last login |

### Change management + governed execution (SOC 2 CC8.1)

| Control | Implementation |
|---|---|
| Governed pipeline | Every skill execution passes the 7-gate pipeline; Tier-1/low-confidence pauses for a human (HITL), restart-safe queue (`app/services/hitl_manager.py`) |
| Deterministic change control | Engineering changes are judged by real checkers, not a model's opinion: SOC2 CC8.1 (peer review + linked change record + green CI), ISO27001 change control (documented rollback + recorded approval), and change-freeze enforcement (`app/compliance/checkers/engineering.py`) |
| Actuation audit | Every applied action has an ActionRecord with before/after state, idempotency key, and a compensator for reversal (`app/services/actuation/actuator.py`) |
| Approval audit | Every HITL decision (in-app or by signed link) lands in the security-event ledger with actor + channel (`app/api/routes/hitl.py`, `approvals.py`) |
| CI gates | backend lint (ruff), tests, bandit BLOCKING, frontend typecheck+build on every push |

### Audit logging (SOC 2 CC7.2, GDPR Art. 30 records)

| Control | Implementation |
|---|---|
| Security-event spine | `record_security_event` captures auth successes/failures, RBAC denials, config changes, exports, HITL decisions, mission actions (`app/core/audit.py`) |
| Sync auditability | Every record crossing the integration boundary (in or out) lands in the SyncLedger - applied, failed, or skipped with reason (`app/models/sync.py`) |
| Notification auditability | Every outbound notification attempt recorded in NotificationDelivery (`app/models/notifications.py`) |
| Export | Audit CSV export endpoints (`app/core/csv_export.py` consumers) |

### Data protection (GDPR Art. 5, 17, 25, 32; PII)

| Control | Implementation |
|---|---|
| PII egress control | Deterministic structured-PII redaction ALWAYS runs before any cloud LLM call (belt) + Presidio NER when available (suspenders); local Ollama calls stay in-region unscrubbed by design (`app/services/llm_router.py::_scrub_for_cloud`, `app/transforms/pii_scrubber.py`; tested in `tests/test_pii_egress.py`) |
| Secrets at rest | Fernet (PBKDF2-HMAC-SHA256 KDF from SECRET_KEY) for connector credentials, TOTP secrets, notification channel configs (`app/services/live_connectors.py`) |
| Erasure (Art. 17) | DSAR erasure endpoint (`app/api/routes/privacy.py::/erasure`) |
| Retention (Art. 5(1)(e)) | Opt-in per-tenant, per-data-class retention windows with an auditable per-class receipt; daily leader-guarded sweep; forbidden-table guard prevents a policy from ever targeting ledgers (`app/services/retention.py`, scheduler `run_retention_sweep`) |
| Data minimization | HITL records strip private context keys before storage; notification reads mask secrets; twin view samples rather than ships full rosters |
| Breach response (Art. 33 readiness) | SOAR intake creates a real Incident, contains (quarantine connector, rotate secrets, disable account at CRITICAL), pages humans through notification channels with severity + actions taken (`app/services/security_response.py`) |

### Availability + resilience (SOC 2 A1)

| Control | Implementation |
|---|---|
| Backups | `scripts/backup_db.py` (pg_dump custom format, retention, integrity check) + restore with plan-first preflight; runbook in `docs/OPS_RUNBOOK.md` |
| Health probes | `/health` (readiness incl. datastore), `/health/live`, optional deep probe |
| Durable queues | Job queue with crash recovery + reaper; outbound sync writes durable with retry |
| Observability | Prometheus metrics + Grafana in compose |

### Vendor / integration risk (SOC 2 CC9.2)

| Control | Implementation |
|---|---|
| Inbound authentication | HMAC-SHA256 over raw body per connector; unguessable connector ids grant nothing alone (`app/services/sync_engine.py`) |
| Honest failure states | No connector / no credentials / unsupported provider are explicit ledgered statuses, never silence |
| Containment | Connector quarantine halts sync both directions in one state change |

## Deterministic statutory checkers

The compliance gate does not ask a model whether an action is lawful. Each
framework tag resolves to a **pure function** `(context: dict) -> CheckResult`:
no LLM, no DB, no network, unit-testable, and it returns the statute it applied
as a citation (`app/compliance/base.py`). One module per department under
`app/compliance/checkers/`, each self-registering with `@register(...)`;
the registry discovers them lazily by walking the package, so adding a
department means dropping a module in, with no central edit
(`app/compliance/registry.py`).

Statuses are deliberately five, not two:

| Status | Meaning | Blocking |
|---|---|---|
| `PASS` | Verified compliant against the cited rule | no |
| `NOT_APPLICABLE` | The action does not touch this regime | no |
| `ADVISORY` | Cannot fully verify (inputs too thin) - surfaced as a warning, never a silent pass | no |
| `BLOCK` | Deterministic violation | yes |
| `UNBACKED` | No checker backs this tag, so the claim is not verified | yes |

### The fail-closed UNBACKED rule

This is the control that matters most, because it closes the hole every
compliance-labelling system has: a tag nobody implemented reading as satisfied.

- `run_checks(frameworks, context)` looks up each requested tag. A tag with **no
  registered checker returns `UNBACKED`, which is `blocking`** - an unbacked
  compliance claim can never read as green.
- A checker that **raises** is converted to `BLOCK`, with the exception text as
  the finding. A broken control is not a passing control.
- A broken *module* (import error) is logged and skipped at discovery, so one bad
  file cannot take the app down; its tags then fall through to `UNBACKED`, which
  is again blocking rather than silent.
- On the pre-execution gate path (`ComplianceEngine.check_before_execution`,
  `app/services/compliance.py`) deterministic checkers run first; any remaining
  tag that was neither judged deterministically, covered by the PCI raw-card
  guard, nor LLM-screened is emitted as an explicit `WARNING` naming the tag as
  unverified, so it surfaces in the result and in provenance instead of
  vanishing. A posture-only label such as GAAP therefore stays visible without
  gridlocking every action.
- If the LLM screening fallback itself cannot run (no provider reachable), it is
  a `BLOCKER` outside DEV_MODE / `ALLOW_SIMULATED_LLM`, and a `WARNING` only in
  those explicitly simulated local modes.

Surfaced honestly to callers: `GET /api/v1/compliance/frameworks` returns exactly
what the platform can deterministically verify, and
`POST /api/v1/compliance/check` runs the checkers against a supplied context
(`app/api/routes/compliance_checks.py`).

### Checker registry

Auto-discovered from `app/compliance/checkers/`. Framework tags are matched
case-insensitively after trimming.

| Department | Framework tag | What it verifies | Citation |
|---|---|---|---|
| Engineering | `SOC2` | Production change has peer review, a linked change record, and passing CI | AICPA TSC CC8.1 (Change Management) |
| Engineering | `ISO27001` | Production change has a documented rollback plan and a recorded approval | ISO/IEC 27001:2022 A.8.32 / A.12.1.2 |
| Engineering | `CHANGE_FREEZE` | No non-emergency change ships inside an active freeze window; emergencies need a named approver | SOC2 CC8.1; ITIL Change Enablement |
| Finance | `SOX` | Financial action has a human approver, and maker is not approver | Sarbanes-Oxley 302/404; COSO control activities |
| Healthcare | `HIPAA_MINIMUM_NECESSARY` | PHI disclosure limited to the minimally necessary fields (treatment, to-individual, and authorized disclosures exempt) | 45 CFR 164.502(b); 45 CFR 164.514(d) |
| Healthcare | `HIPAA_AUTHORIZATION` | Non-TPO disclosure carries an authorization that is present, signed, unexpired, and unrevoked | 45 CFR 164.508 |
| Healthcare | `HIPAA_DEIDENTIFICATION` | A payload *claimed* de-identified carries none of the 18 Safe Harbor identifiers | 45 CFR 164.514(b) |
| Healthcare | `PART2` | Substance-use-disorder records (program-sourced or ICD-10 F10-F19) have specific signed consent | 42 CFR Part 2 |
| HR | `EEOC` | Four-fifths adverse-impact test on real cohort selection rates | EEOC Uniform Guidelines 29 CFR 1607.4(D) |
| HR | `FLSA` | Non-exempt hours over 40 paid at 1.5x or better | FLSA 29 U.S.C. 207(a) |
| HR | `I9` | Section 1 by first day of work, Section 2 within 3 business days | 8 U.S.C. 1324a; 8 CFR 274a.2 |
| Legal | `CONFLICT_OF_INTEREST` | New-matter parties do not overlap the adverse-party list | ABA Model Rule 1.7 |
| Legal | `LEGAL_HOLD` | Records under an active hold are neither deleted nor modified | FRCP 37(e) |
| Legal | `RETENTION_SCHEDULE` | No disposal before the retention schedule allows it | 18 U.S.C. 1519; applicable retention schedule |
| Legal | `CONTRACT_CLAUSE` | Required clauses are present (canonicalized clause names) | ABA Model Rule 1.1; contract standards |
| Lending | `ECOA` | Adverse action carries a Reg B notice with specific principal reasons | ECOA 15 U.S.C. 1691; 12 CFR 1002.9 |
| Lending | `FAIR_LENDING` | Disparate-impact screen on approval rates across protected classes (four-fifths) | ECOA/Reg B; Fair Housing Act; 29 CFR 1607.4(D) |
| Lending | `TILA` | APR and finance-charge disclosure present and consistent | TILA 15 U.S.C. 1601; Reg Z 12 CFR 1026 |
| Lending | `FDCPA` | Collection contact respects the statutory communication limits | FDCPA 15 U.S.C. 1692 |
| Operations | `CHANGE_MANAGEMENT` | Approver segregation plus a linked ticket on every change | SOX 404 ITGC; COBIT BAI06 |
| Operations | `INCIDENT_POSTMORTEM` | SEV1/SEV2 cannot close without a postmortem | SOX 404 ITGC; COBIT DSS02/DSS03 |
| Operations | `BACKUP_RETENTION` | Restore and delete respect the backup/retention policy | SOX 404 ITGC; COBIT DSS04/DSS01 |
| Procurement | `THREE_WAY_MATCH` | PO, goods receipt, and invoice agree before payment | SOX 404 three-way match; COSO purchasing controls |
| Procurement | `SEGREGATION_OF_DUTIES` | Requester, approver, and receiver are distinct identities | Sarbanes-Oxley 404; COSO segregation of duties |
| Procurement | `SPEND_AUTHORIZATION` | Spend sits inside the approver's delegated authority | COSO authorization controls; SOX 404 DoA matrix |
| Procurement | `OFAC_SANCTIONS` | Vendor screened against denied-parties/sanctions lists | OFAC 31 CFR Chapter V (Parts 500-599); EO 13224 |
| Sales / CRM | `GDPR` | A lawful basis under Art 6 exists for the processing | GDPR Art 6 (Regulation (EU) 2016/679) |
| Sales / CRM | `CCPA` | A consumer opt-out of sale or sharing is honoured | CCPA Cal. Civ. Code 1798.120 |
| Sales / CRM | `TCPA` | No call or SMS to a do-not-contact or opted-out number | TCPA 47 U.S.C. 227 |
| Sales / CRM | `DSAR` | Data-subject request answered inside the statutory deadline | GDPR Art 12(3); CCPA Cal. Civ. Code 1798.130 |
| Support | `PII_REDACTION` | Outbound text carries no card PAN, SSN, or API key | PCI-DSS v4.0 Req. 3.3; FTC Safeguards Rule 16 CFR 314 |
| Support | `CALL_RECORDING_CONSENT` | Two-party-consent recording has consent on file | Cal. Penal Code 632 (CIPA); 18 U.S.C. 2511 |
| Support | `SLA_BREACH` | Ticket SLA breach (advisory by design, not statutory) | Internal support SLA policy |

Regulated-vertical gates are wired straight into the vertical services, not
bolted on after the fact: PHI disclosure runs the four healthcare checkers
(`app/healthcare/services/phi_disclosure.py`), underwriting and adverse action
run the lending checkers (`app/lending/services/underwriting.py`), and
source-to-pay runs the procurement checkers plus the real three-way match
(`app/procurement/services/source_to_pay.py`).

## Framework tags on skills

Skills carry `compliance_tags` (SOX, GDPR, HIPAA, CCPA, EEOC, PCI, EU_AI_ACT,
SEC, SOC2, ISO27001); the regulatory engine classifies deployed-skill risk
EU-AI-Act-style and assembles per-framework evidence packs from the real
ledgers (`app/services/regulatory.py`).

A tag is only a *label* until a checker backs it. `GET /compliance/frameworks`
is the honest boundary between the two: tags on that list are deterministically
verified, tags absent from it fail closed as `UNBACKED` at the gate. PCI is
normalized across the three spellings seen in the wild (`PCI`, `PCI-DSS`,
`PCI_DSS`) so a real-world tag cannot slip past the raw-card guard.

## Known gaps (the honest list)

1. **Certification is organizational.** SOC 2 Type II / ISO 27001 require an
   external auditor observing controls over a period, plus written policies,
   vendor DPAs, and personnel processes. This repo provides the technical
   controls and evidence exports.
2. **Disk-level encryption at rest** depends on the deployment (cloud-volume
   or filesystem encryption). Field-level Fernet covers secrets; business rows
   rely on the storage layer. Documented in the ops runbook.
3. **GDPR DPO / RoPA documents** are templates the operating company must own;
   Art. 30 records can be generated from the audit spine but the legal
   document is organizational.
4. **Workday/Salesforce data-processing scope** activates per customer with
   their credentials; until then those controls are dormant by definition.
5. **Not every tag has a deterministic checker yet.** The granular HIPAA tags
   (`HIPAA_MINIMUM_NECESSARY`, `HIPAA_AUTHORIZATION`, `HIPAA_DEIDENTIFICATION`,
   `PART2`) are deterministic; a bare `HIPAA` tag still falls to LLM screening,
   which is labelled as screening rather than a statutory test. Posture-only
   labels (EU_AI_ACT, SEC, GAAP) surface as unverified warnings by design. The
   checker registry is the list of what is real; nothing outside it is claimed.
6. **The checkers verify the facts they are given.** A checker is a pure
   function over the structured context an agent assembles: it is a real
   statutory test, not an attestation that the upstream data was complete.
   Thin inputs return ADVISORY, never a silent pass, but garbage-in remains the
   ingesting connector's problem, not the gate's.
7. **Starlette dependency ceiling**: several upstream CVEs are unreachable
   because no FastAPI release supports Starlette 1.x yet; documented, and the
   auth gates read `scope["path"]` to neutralize the Host-header class
   (see CHANGELOG v1.1.x notes).
