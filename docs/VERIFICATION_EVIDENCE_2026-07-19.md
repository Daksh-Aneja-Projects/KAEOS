# Post-Remediation Verification Evidence — 2026-07-19

Evidence backing the L10 audit-remediation changeset (`a002dfd..HEAD`). Run on a
Windows dev box (Docker/Postgres not installed; a userspace PostgreSQL 16.4 was
downloaded to prove RLS, and an isolated venv with `starlette==0.38.6` was used
to boot the app around the global FastAPI/Starlette skew).

## V1 — Full E2E suite: PASS
`pytest tests/e2e/` against a live server (SQLite) with real local Qwen
(`qwen2.5-coder:7b`):

```
422 passed, 4 skipped, 0 failed  (0:58:32)
```

## V2 — PostgreSQL Row-Level Security: VERIFIED
Ran the app's real `ensure_app_role` + `ensure_rls_policies` + `assert_rls_effective`
on PostgreSQL 16.4, with the app connecting as the non-owner `kaeos_app` role and
tables owned by a superuser (as in production). Seeded two tenants' rows as owner,
then queried as `kaeos_app` with the per-transaction tenant binding:

| Check | Result |
|---|---|
| `assert_rls_effective` (app role is non-owner; `tenant_isolation` policies present) | PASS |
| session bound to `tenant_acme` | sees ONLY the acme row |
| session bound to `tenant_realco` | sees ONLY the realco row |
| session with NO tenant context | sees NOTHING (fail-closed) |
| INSERT a row for another tenant (WITH CHECK) | BLOCKED |

Cross-tenant reads are impossible and cross-tenant writes are rejected by Postgres
itself, independent of application query filters. (Note: pgvector was not present
in the vanilla binaries, so the ~1 vector/semantic-memory table subset was excluded
from this run; RLS on the ~179 normal tenant tables was verified.)

## V3 — Independent adversarial code review: CLEAN
A separate reviewer traced the full diff: no Critical/High regressions; fail-closed
governance chain verified end-to-end (no fail-open path); migration baseline builds
181 tables; auth sound (last-admin guard, JWT); subagent-written files preserved
their failure-fallback contracts; tenant-registry signatures match the real vector
store. Only flag: the BYOK Fernet-key change (documented below) is a conscious
breaking change for pre-existing encrypted credentials.

## V4 — Migration integrity + dependencies
- `python -m scripts.check_migration_drift` → "models define 181 tables; migrations
  built 181 of them." (fresh `alembic upgrade head` builds the whole schema.)
- `python -m scripts.check_tenant_integrity` → correctly flags orphaned tenant_ids.
- Dependency note: a clean install must run on the Docker image's pinned Python
  (3.11/3.12); `psycopg2-binary` has no wheel for Python 3.14. `starlette==0.38.6`
  is now pinned.

## Residual items before onboarding a real client (see UPGRADE_NOTES_post_audit.md)
1. Run the full E2E suite against **Postgres + pgvector** (this run was SQLite for
   the suite; RLS was proven separately on Postgres without pgvector).
2. Decide on **BYOK re-encryption** if any environment already stores connector
   credentials (the at-rest key derivation changed).
3. Load test and an independent security/pen-test pass.
