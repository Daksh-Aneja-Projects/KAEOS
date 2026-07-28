# Security Model

Back to the [README](../README.md). Related: [Known limitations](KNOWN_LIMITATIONS.md) |
[Deployment](DEPLOYMENT.md) | [Connectors](CONNECTORS.md)

To report a security vulnerability, see [SECURITY.md](../SECURITY.md).

## Security controls

| Feature | Implementation |
|---------|----------------|
| **Authentication** | JWT Bearer tokens + API Keys (hashed with SHA-256) |
| **Authorization** | Role-based (`viewer` / `operator` / `admin`) via `require_role`/`require_service_or_role`, under a **default-deny** policy: every state-changing endpoint must be gated or on a short reviewed allowlist, enforced by `tests/test_default_deny.py`. 199 of 212 write endpoints carry an explicit gate today; the remaining 13 are the reviewed allowlist (public auth routes, HMAC-authenticated external ingest, MFA self-service, viewer self-actions, read-only explain/chat) and none mutate persistent business state (see [Known limitations](KNOWN_LIMITATIONS.md)) |
| **Tenant Isolation** | Two layers: `Depends(get_tenant_id)` filters on every route, PLUS Postgres Row-Level Security policies on every tenant table (fails closed; verified by `scripts/verify_rls.py`) |
| **Rate Limiting** | 200 req/min per tenant via `RateLimitMiddleware`; Redis-backed shared fixed-window counter (one limit across all workers/replicas) when Redis is reachable, in-memory per-process fallback for single-instance dev |
| **CORS** | Configurable per-environment origin allowlist |
| **Audit Trail** | `SecurityAuditLog` records auth successes/failures (with lockout), RBAC denials, HITL decisions, config changes, connector and export actions, wired to real runtime events across the auth service and ~30 route and service modules. Best-effort writer (never blocks a request). Separate from the AI-decision provenance ledger, which is also live |
| **HITL Gate** | Autonomy is the default: once a decision's confidence clears a configurable threshold (default 0.82) it runs without a human. Decisions below the threshold, plus high-consequence action classes (e.g. production deploys, customer-facing documents), route to human approval before execution. Approvals are role-gated (operator/admin) and attributable to the approver; the gate is blocking and tenant-isolated |
| **Provenance** | Hash-chained, tamper-evident `ProvenanceLedger` for every AI decision with full lineage; explainable by design |
| **Prompt-injection screening** | Untrusted/connected content is scanned by `app/services/prompt_guard.py` (instruction-override, role-manipulation, exfiltration, guardrail-bypass, command/SQL smuggling, fake-role-turn, encoded-payload); matched command spans are redacted and the text is fenced as data before it reaches an LLM. Wired into ingestion (high-risk signals quarantined). Defense in depth, layered with source-authority weighting and the HITL gates |
| **Data erasure** | `POST /privacy/erasure` tombstones PII, deletes stored blobs (`blob_store`: local FS + best-effort S3/GCS), purges vector embeddings, and journals the erasure; `POST /privacy/erasure/replay` re-applies erasures after a backup restore (no raw PII stored - email matched by SHA-256) |
| **Audit readiness** | `GET /compliance/controls` returns a controls-evidence report mapping implemented controls to SOC 2 / ISO 27001 / GDPR / SOX with code+test evidence; external attestation and pen-test are listed but never marked satisfied |
| **Secrets** | API keys stored as SHA-256 hashes; plaintext never persisted |

## Multi-tenancy

KAEOS is fully multi-tenant from the ground up, enforced at **two independent layers**:

**1. Application filters.** Every API request is authenticated via JWT. The `TenantMiddleware`
extracts `tenant_id` from the verified token and injects it into request state via
`Depends(get_tenant_id)`; queries filter on it explicitly.

```python
# Every route endpoint looks like this:
@router.get("/departments")
async def list_departments(
    tenant_id: str = Depends(get_tenant_id),  # Enforced on every request
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Department).where(Department.tenant_id == tenant_id)
    )
```

**2. Postgres Row-Level Security (the backstop that doesn't depend on discipline).** A
hand-written filter can be forgotten - and has been. Under Postgres, every tenant-scoped
table carries a `tenant_isolation` policy comparing `tenant_id` to the transaction-bound
`app.tenant_id` setting: the database itself refuses to return another tenant's rows, even
to a deliberately unfiltered `SELECT *`. An unset tenant context matches **nothing** (fails
closed). The application connects as the non-owner `kaeos_app` role - Postgres exempts
table owners from their own policies, so the compose files deliberately split the app
connection from the owner (migrations/seeding) connection.

Verify on any deployment:

```bash
DATABASE_URL=<kaeos_app url> KAEOS_OWNER_DB_URL=<owner url> python scripts/verify_rls.py
# -> RLS ENFORCED
```

SQLite (local dev) has no RLS; there the application filters are the only layer - which is
exactly why production runs Postgres.

## Enterprise SSO (OpenID Connect)

Real OIDC single sign-on: the full Authorization Code flow with IdP discovery,
`state`+`nonce` CSRF/replay protection, **RS256 `id_token` verification against the
IdP's JWKS**, and just-in-time user provisioning that mints a normal KAEOS session.
Works with Azure AD, Okta, Google, and Auth0. Per-tenant IdP config
(`/auth/sso/connections`, ADMIN-gated) stores the client secret Fernet-encrypted at
rest and never returns it; the login endpoints (`/auth/sso/oidc/authorize` ->
`/callback`) are the only pre-auth surface. SAML is on the roadmap.
