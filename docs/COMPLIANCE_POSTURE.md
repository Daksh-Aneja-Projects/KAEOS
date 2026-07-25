# KAEOS Compliance Posture

Technical-control map for SOC 2, GDPR, and PII handling. Every control listed
here is implemented and verifiable in this repository (file references given).
This document is the evidence map an auditor starts from.

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
| Department-scoped access | `users.department` confines a user to one department's operational surface; enforced at router mounts + per-row (`require_department`, `check_department_scope`); cross-domain aggregates deliberately readable (documented IP decision) |
| MFA | TOTP second factor (RFC 6238), secret Fernet-encrypted at rest (`app/models/mfa.py`, migration 0019) |
| SSO / provisioning | OIDC SSO, SAML, SCIM 2.0 provisioning (`app/api/routes/sso.py`, `scim.py`) |
| Service-to-service auth | `X-Service-Token` gate on internal mutations (`require_service_or_role`) |
| API keys | DB-backed, hashed at rest, revocable (`app/models/api_key.py`) |
| Access review evidence | `GET /auth/users/export.csv` - auditor-ready CSV of every account with role, department scope, status, last login |

### Change management + governed execution (SOC 2 CC8.1)

| Control | Implementation |
|---|---|
| Governed pipeline | Every skill execution passes the 7-gate pipeline; Tier-1/low-confidence pauses for a human (HITL), restart-safe queue (`app/services/hitl_manager.py`) |
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

## Framework tags on skills

Skills carry `compliance_tags` (SOX, GDPR, HIPAA, CCPA, EEOC, PCI, EU_AI_ACT,
SEC, SOC2, ISO27001); the regulatory engine classifies deployed-skill risk
EU-AI-Act-style and assembles per-framework evidence packs from the real
ledgers (`app/services/regulatory.py`).

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
5. **Starlette dependency ceiling**: several upstream CVEs are unreachable
   because no FastAPI release supports Starlette 1.x yet; documented, and the
   auth gates read `scope["path"]` to neutralize the Host-header class
   (see CHANGELOG v1.1.x notes).
