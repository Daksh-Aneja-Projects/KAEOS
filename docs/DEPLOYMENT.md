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
  is empty, no admin is seeded (deliberate: a public deployment never ships
  with known credentials). You can't lock yourself out: the last active admin
  in a tenant can't be deactivated.

## Production configuration (the app fails fast on insecure config)
- Set a strong `SECRET_KEY` (≥16 chars) and a unique `ADMIN_SECRET`.
- `DATABASE_URL` must be **PostgreSQL**. The app refuses to boot on SQLite in a
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
  (The fictional demo dataset is skipped in a production-like environment anyway,
  but set it explicitly rather than relying on the guard.)
- Front the stack with TLS; override every `*_PASSWORD` in `docker-compose.yml`
  via environment/secrets (the compose defaults are for local dev only).
- `CONTENT_SECURITY_POLICY` (optional): empty uses the hardened middleware
  default, which sets a `connect-src` permitting the SPA to reach the
  cross-origin API and WebSocket. (It previously had none, which blocked every
  XHR/WS from the browser.) In production, set this to pin `connect-src` to your
  actual API and WebSocket origins instead of the broader default.
- `FINANCE_BASE_CURRENCY` (default `USD`): the tenant base/reporting currency.
  Every journal line is converted to it at post time via `fin_fx_rates`, and all
  GL reporting (trial balance, income statement, balance sheet, cash flow)
  aggregates `amount_in_base` rather than summing native debit/credit columns. A
  reversal re-converts at the ORIGINAL entry date so base amounts offset exactly.
  Set it **before** posting anything: changing it later does not retroactively
  re-convert posted lines, so it is a deliberate re-statement, not a toggle.
- `METRICS_ROLLUP_INTERVAL_MINUTES` (default `60`): the leader-guarded rollup
  that snapshots each active tenant's safe-autonomy rate, execution volume and
  cost into `ts_metric_samples`. It is registered on the shared scheduler, so it
  runs only on the elected leader and is idempotent per bucket (a unique
  constraint is the backstop against a racing second leader). A metric with no
  underlying data is stored as null, never as a fabricated `0`.

## Database migrations
- The chain runs to head **`0044_tenant_branding`**. New this cycle:
  `0040_fin_fx_rates` (multi-currency GL: `fin_fx_rates` +
  `fin_journal_lines.amount_in_base`), `0041_healthcare_tables` (`hlth_*`),
  `0042_lending_vertical` (`lnd_*`), `0043_metrics_timeseries`
  (`ts_metric_samples`), `0044_tenant_branding` (`brand_tenant_branding`). All
  are additive and inspector-guarded, and enable RLS on Postgres.
- Fresh database: `alembic upgrade head` builds the full schema (verified by
  `scripts/check_migration_drift.py`), or the app self-bootstraps the schema +
  `kaeos_app` role + RLS on first boot.
- **Validate the chain on real Postgres before deploying, not just SQLite.**
  SQLite is permissive enough to hide dialect bugs that only fail in production:
  a `boolean = integer` comparison in `0025` ran clean on SQLite and was rejected
  by Postgres. Run `alembic upgrade head` against a scratch
  `pgvector/pgvector:pg16` container as part of the release check.
- **Alembic revision ids must stay <= 32 characters.**
  `alembic_version.version_num` is `VARCHAR(32)`; a longer id inserts on SQLite
  and fails on Postgres. Two ids were renamed for this reason.
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
automatic re-encryption; the old key material is not recoverable by design).
Fresh installs are unaffected.

## CI / integrity tooling (recommended)
- `python -m scripts.check_migration_drift` fails if migrations can't build the
  full model schema.
- `python -m scripts.check_tenant_integrity --strict` fails if any row carries a
  `tenant_id` not present in the `tenants` registry (orphan detection).
- The GitHub Actions CI runs the non-Ollama E2E suite against PostgreSQL + pgvector.

## Health checks and load balancers
- Point the load balancer / uptime monitor at **`/status`**: public, no auth,
  root-mounted like `/health`. It reports `version`, `uptime_seconds` and
  db/redis/llm reachability, and returns **503** when the database (the only
  critical dependency) is unreachable so the balancer can drain the instance.
- It exposes no per-tenant data and deliberately omits the platform
  safe-autonomy rate: that is a business metric, and its cross-tenant aggregate
  is an unindexed full scan (`skill_executions` is indexed tenant_id-leading),
  which would be a DoS amplifier on an auth-free endpoint. It lives on the
  super-admin-gated `/api/v1/ops/*` operator console instead (tenants, tenant
  detail, overview), which is guarded by the `ADMIN_SECRET` super-admin
  dependency and reads cross-tenant via the owner/maintenance session.
- `/health` remains the richer, backend-by-backend view for humans.

## Pre-launch checklist for a production/client deployment
- [ ] Run `alembic upgrade head` against a real `pgvector/pgvector:pg16`
      instance (not SQLite) and confirm it lands on `0044_tenant_branding`.
- [ ] Run the full E2E suite against your Postgres+pgvector stack.
- [ ] Load test at your expected concurrency (the built-in rate limiter is a
      Redis-backed shared limiter across replicas; make sure every replica points
      at the same Redis, or it falls back to a per-process in-memory window).
- [ ] Independent security / penetration test.
- [ ] Decide the connector-credential re-encryption step above if upgrading.
- [ ] Set `FINANCE_BASE_CURRENCY` before any GL activity, and load the
      `fin_fx_rates` your tenant needs; unconverted foreign lines have nothing to
      report against.
- [ ] Confirm `/status` is reachable from the load balancer and that a stopped
      database really does turn it 503.
- [ ] Confirm exactly one replica wins leadership, so the metrics rollup and the
      other singleton loops run once, not N times.
