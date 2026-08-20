# Security Model

Back to the [README](../README.md). Related: [Known limitations](KNOWN_LIMITATIONS.md) |
[Deployment](DEPLOYMENT.md) | [Connectors](CONNECTORS.md)

To report a security vulnerability, see [SECURITY.md](../SECURITY.md).

## Security controls

| Feature | Implementation |
|---------|----------------|
| **Authentication** | JWT Bearer tokens + API Keys (hashed with SHA-256) |
| **Authorization** | Role-based (`viewer` / `operator` / `admin`) via `require_role`/`require_service_or_role`, under a **default-deny** policy: every state-changing endpoint must be gated or on a short reviewed allowlist, enforced by `tests/test_default_deny.py`. 293 of 308 mutating paths carry an explicit gate today; the remaining 15 are the reviewed allowlist (public auth routes, the SAML ACS, HMAC-authenticated external ingest, the signature-verified Stripe webhook, MFA self-service, viewer self-actions, read-only explain/chat/compliance-check) and none mutate persistent business state (see [Known limitations](KNOWN_LIMITATIONS.md)). A companion test fails loudly if the route walker ever stops discovering routes, so the lint cannot pass vacuously |
| **Tenant Isolation** | Two layers: `Depends(get_tenant_id)` filters on every route, PLUS Postgres Row-Level Security policies on every tenant table (fails closed; verified by `scripts/verify_rls.py`) |
| **Rate Limiting** | 200 req/min per tenant via `RateLimitMiddleware`; Redis-backed shared fixed-window counter (one limit across all workers/replicas) when Redis is reachable, in-memory per-process fallback for single-instance dev |
| **CORS** | Configurable per-environment origin allowlist. `"*"` is REFUSED outside `DEV_MODE`: the app mounts `CORSMiddleware` with `allow_credentials=True`, so a wildcard is reflected back as the caller's own origin and any site a signed-in operator visits could read their authenticated responses. Enforced at boot by `Settings.validate_production_security()` |
| **Audit Trail** | `SecurityAuditLog` records auth successes/failures (with lockout), RBAC denials, HITL decisions, config changes, connector and export actions, wired to real runtime events across the auth service and ~30 route and service modules. Best-effort writer (never blocks a request). Separate from the AI-decision provenance ledger, which is also live |
| **HITL Gate** | Autonomy is the default: once a decision's confidence clears a configurable threshold (default 0.82) it runs without a human. Decisions below the threshold, plus high-consequence action classes (e.g. production deploys, customer-facing documents), route to human approval before execution. Approvals are role-gated (operator/admin) and attributable to the approver; the gate is blocking and tenant-isolated |
| **Provenance** | Signed (HMAC-SHA256, key derived from `SECRET_KEY`), hash-chained, append-only `ProvenanceLedger` for every AI decision: one scheme across all writers, explicit parent pointers, per-tenant chains, DB-serialized appends (no forks on any worker count), an end-to-end verifier, and on Postgres UPDATE/DELETE revoked from the app role. Entries predating the unification are reported as legacy (unverifiable), never as tampering. Rotating `SECRET_KEY` invalidates verification of previously signed rows - export first |
| **Prompt-injection screening** | Untrusted/connected content is scanned by `app/services/prompt_guard.py` (instruction-override, role-manipulation, exfiltration, guardrail-bypass, command/SQL smuggling, fake-role-turn, encoded-payload); matched command spans are redacted and the text is fenced as data before it reaches an LLM. `wrap_untrusted` also neutralises any occurrence of KAEOS's **own fence markers** inside the payload (open or close, with or without a slash or whitespace, case-insensitive) - emitting a close marker and then writing trusted-channel instructions was a real escape from inside the fence. Wired into ingestion (high-risk signals quarantined). Defense in depth, layered with source-authority weighting and the HITL gates |
| **Security headers / CSP** | `SecurityHeadersMiddleware` sets `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, HSTS outside DEV_MODE, and a Content-Security-Policy. The XSS-critical directives stay locked (`script-src 'self'`, `object-src 'none'`, `base-uri 'self'`, `form-action 'self'`, `frame-ancestors 'none'`); `connect-src` allows the cross-origin API and WebSocket, because the SPA and the API are on different ports/hosts in every shipped config and `'self'` alone blocked all XHR/WS. Operators with a fixed API domain should pin it via the `CONTENT_SECURITY_POLICY` setting. The `<meta http-equiv>` policy in `frontend/index.html` (which guards the statically served SPA) is kept in sync with the middleware default |
| **Platform-operator boundary** | Cross-tenant fleet reads live only under `/api/v1/ops/*`, gated at the router (`dependencies=[Depends(require_superadmin)]`, so a new route cannot ship ungated) on the `ADMIN_SECRET` header, compared in constant time. Unset secret returns 503 (endpoint disabled, never a shared default); wrong secret returns 403. Those routes read through the owner/maintenance session, which bypasses RLS by design, so the secret is the only thing standing between a caller and every tenant. A tenant JWT never grants it |
| **White-label branding** | `GET /api/v1/branding` is readable by any authed tenant user (the SPA needs a theme); `PUT` is admin-only and fail-closed: colours must match `^#[0-9a-fA-F]{6}$`, and `logo_url` must parse to an absolute `http(s)` URL with a host, so `javascript:`, `data:`, and relative values are rejected rather than rendered into the login shell. Every write lands in the security-event ledger as a `CONFIG_CHANGE` with the actor |
| **Data erasure** | `POST /privacy/erasure` tombstones PII, deletes stored blobs (`blob_store`: local FS + best-effort S3/GCS), purges vector embeddings, and journals the erasure; `POST /privacy/erasure/replay` re-applies erasures after a backup restore (no raw PII stored - email matched by SHA-256) |
| **Audit readiness** | `GET /compliance/controls` returns a controls-evidence report mapping implemented controls to SOC 2 / ISO 27001 / GDPR / SOX with code+test evidence; external attestation and pen-test are listed but never marked satisfied |
| **Secrets** | API keys stored as SHA-256 hashes; plaintext never persisted |
| **Boot-time config gate** | `Settings.validate_production_security()` runs in the startup lifespan and refuses to serve if it returns anything: placeholder or short `SECRET_KEY`, placeholder `ADMIN_SECRET` or `CONNECTOR_ENCRYPTION_KEY`, a weak `ADMIN_PASSWORD`, a wildcard `CORS_ORIGINS`, SQLite as the production database, and `ADMIN_TENANT` left at the demo `tenant_acme`. That last one is a data-integrity control, not a login control: every fixture path in the tree writes to `tenant_acme` by name, so a deployment that kept the default would hold real customer records in the tenant the demo seeders target. Each control is pinned by `tests/test_production_config_guards.py` |
| **No dead auth paths** | The legacy HMAC-token path was removed rather than left dormant: an unused authentication route is an unmonitored one. Demo/fictional seeding is skipped entirely in production-like environments, so a real deployment never ships with a seeded tenant |

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

**Every new table joins the policy, including the regulated verticals.** The rule is not
"remember to add RLS" - each migration that creates a tenant table calls
`rls_enable_statements(...)` under a Postgres guard, so the multi-currency FX rates
(`fin_fx_rates`, 0040), the PHI tables (`hlth_encounters`, `hlth_phi_disclosures`,
`hlth_consent_records`, `hlth_clinical_tasks`, 0041), the lending tables
(`lnd_loan_applications`, `lnd_underwriting_decisions`, `lnd_adverse_action_notices`,
`lnd_credit_policies`, 0042), the metric series (`ts_metric_samples`, 0043) and tenant
branding (`brand_tenant_branding`, 0044) are all isolated at the database, not just in
the query.

**And a backstop for the backstop.** `init_db` runs a sweep after `create_all` that finds
any table carrying `tenant_id` with no isolation policy (excluding the small documented
`GLOBAL_TABLES` set: `users`, `tenants`, `alembic_version`, and the pre-tenant-context key
rows) and installs the policy, logging a WARNING naming every table it had to repair. A
table reaching that point escaped its migration, and that is worth seeing rather than
silently leaking.

Verify on any deployment:

```bash
DATABASE_URL=<kaeos_app url> KAEOS_OWNER_DB_URL=<owner url> python scripts/verify_rls.py
# -> RLS ENFORCED
```

SQLite (local dev) has no RLS; there the application filters are the only layer - which is
exactly why production runs Postgres.

## Public surface: `/status`

`/status` is root-mounted, unauthenticated, and read-only. It reports process liveness,
uptime, the app version, and reachability of db / redis / llm, returning 503 when the
database (the only critical dependency) is down so a load balancer can act on it.

It deliberately does **not** report the platform safe-autonomy rate. That is a business
metric, and its cross-tenant aggregate is an unindexed full scan of `skill_executions`
(whose index is tenant_id-leading), which would make an auth-free endpoint a DoS
amplifier. The blended number lives on the super-admin-gated `/api/v1/ops/overview`
instead, and it honours the honesty contract: no executions in the window returns null,
never a fabricated 0.

## Enterprise SSO (OpenID Connect)

Real OIDC single sign-on: the full Authorization Code flow with IdP discovery,
`state`+`nonce` CSRF/replay protection, **RS256 `id_token` verification against the
IdP's JWKS**, and just-in-time user provisioning that mints a normal KAEOS session.
Works with Azure AD, Okta, Google, and Auth0. Per-tenant IdP config
(`/auth/sso/connections`, ADMIN-gated) stores the client secret Fernet-encrypted at
rest and never returns it; the login endpoints (`/auth/sso/oidc/authorize` ->
`/callback`) are the only pre-auth surface.

Real SAML 2.0 as well: KAEOS is a Service Provider in the SP-initiated
HTTP-Redirect/POST profile. SP metadata is published at
`/auth/sso/saml/metadata`; the ACS (`/auth/sso/saml/acs`) verifies the IdP's
XML-DSig signature (`signxml`, pure Python) against the configured certificate,
reads only the *verified* subtree (defeating XML Signature Wrapping), and
enforces Status, validity windows (with clock skew), AudienceRestriction ==
this SP, Recipient == this ACS, `InResponseTo` == the request we issued, and
single-use assertion IDs. Encrypted assertions are refused rather than accepted
unverified. Both protocols provision through one path, so JIT provisioning and
role mapping are identical.
