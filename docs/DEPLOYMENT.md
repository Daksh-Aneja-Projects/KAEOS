# Deployment & Upgrade Guide

How to run KAEOS in production, and the one-time steps when upgrading an
existing install. For local development, see the Quick Start in the README.

## Admin account
- The root admin is provisioned at startup from `.env`:
  ```
  ADMIN_EMAIL=you@yourco.com
  ADMIN_PASSWORD=<a strong password>
  ADMIN_DISPLAY_NAME=Your Name
  ADMIN_TENANT=tenant_acme
  ```
- There is **no** default/public login. Outside `DEV_MODE`, if `ADMIN_PASSWORD`
  is empty, no admin is seeded (deliberate — a public deployment never ships
  with known credentials). You can't lock yourself out: the last active admin
  in a tenant can't be deactivated.

## Production configuration (the app fails fast on insecure config)
- Set a strong `SECRET_KEY` (≥16 chars) and a unique `ADMIN_SECRET`.
- `DATABASE_URL` must be **PostgreSQL** — the app refuses to boot on SQLite in a
  production environment (SQLite has no row-level security). Use the
  `pgvector/pgvector:pg16` image; plain Postgres lacks the `vector` type.
- The app must connect as the **non-owner** `kaeos_app` role so RLS applies; set
  `KAEOS_OWNER_DB_URL` for the owner/maintenance connection. At startup
  `assert_rls_effective()` verifies the app role is not a table owner and that
  `tenant_isolation` policies exist, and **fails closed in production** if RLS is
  inert. `scripts/verify_rls.py` is an additional gate.
- Keep `ALLOW_SIMULATED_LLM=false`. When no LLM provider is reachable, the
  governance gates (compliance/fairness/debate/HITL) **fail closed** (deny /
  route to a human) rather than proceeding on a simulated response.
- Set `SEED_DEMO_DATA=false` so dashboards reflect only genuinely ingested data.
- Front the stack with TLS; override every `*_PASSWORD` in `docker-compose.yml`
  via environment/secrets (the compose defaults are for local dev only).

## Database migrations
- Fresh database: `alembic upgrade head` builds the full schema (verified by
  `scripts/check_migration_drift.py`), or the app self-bootstraps the schema +
  `kaeos_app` role + RLS on first boot.
- **Upgrading an existing database** that predates the single-baseline migration:
  re-stamp once:
  ```
  alembic stamp 0001_baseline
  # if alembic can't locate an old revision id, purge and re-stamp:
  python -c "from alembic.config import Config; from alembic import command; command.stamp(Config('alembic.ini'), '0001_baseline', purge=True)"
  ```

## Upgrading: connector credentials (breaking, only if you stored any)
The at-rest encryption for BYOK connector credentials uses a PBKDF2-derived key.
If you are upgrading a deployment that already stored connector credentials under
an older build, those secrets must be **re-entered** after upgrade (there is no
automatic re-encryption — the old key material is not recoverable by design).
Fresh installs are unaffected.

## CI / integrity tooling (recommended)
- `python -m scripts.check_migration_drift` — fails if migrations can't build the
  full model schema.
- `python -m scripts.check_tenant_integrity --strict` — fails if any row carries a
  `tenant_id` not present in the `tenants` registry (orphan detection).
- The GitHub Actions CI runs the non-Ollama E2E suite against PostgreSQL + pgvector.

## Pre-launch checklist for a production/client deployment
- [ ] Run the full E2E suite against your Postgres+pgvector stack.
- [ ] Load test at your expected concurrency (the built-in rate limiter is
      per-process; put a shared limiter in front for multi-instance deploys).
- [ ] Independent security / penetration test.
- [ ] Decide the connector-credential re-encryption step above if upgrading.
