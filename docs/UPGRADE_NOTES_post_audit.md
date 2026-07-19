# Post-Audit Upgrade / Operator Notes

Operational steps required when deploying the L10 audit-remediation changes
(`a002dfd..HEAD`). Most are one-time. Read this before upgrading an existing
environment — several items are **breaking** for an existing database.

## 1. Admin login (BREAKING: the old public demo login is gone)
- The hardcoded `demo@kaeos.ai / demo123` account no longer works; any legacy
  copy is auto-disabled at startup.
- Set in `.env`:
  ```
  ADMIN_EMAIL=you@yourco.com
  ADMIN_PASSWORD=<a strong password>
  ADMIN_DISPLAY_NAME=Your Name
  ADMIN_TENANT=tenant_acme
  ```
- Outside DEV_MODE, if `ADMIN_PASSWORD` is empty, **no admin is seeded** (by
  design — no public credentials ever ship). Set it and restart.

## 2. Database migrations (BREAKING for existing DBs: re-stamp required)
- The 8 order-dependent migrations were replaced by a single baseline
  `0001_baseline` that builds the full schema. Old migrations are archived under
  `backend/alembic/legacy_versions_pre_baseline/`.
- **Existing database** (already has the schema): run once:
  ```
  alembic stamp 0001_baseline
  ```
  If alembic errors with "Can't locate revision …", the DB carries an old
  revision id; stamp with purge:
  ```
  python -c "from alembic.config import Config; from alembic import command; command.stamp(Config('alembic.ini'), '0001_baseline', purge=True)"
  ```
- **Fresh database**: `alembic upgrade head` now builds all ~181 tables (+
  pgvector + RLS on Postgres). Verified by `scripts/check_migration_drift.py`.

## 3. BYOK connector credentials (BREAKING if any are already stored)
- The at-rest encryption key derivation changed from a single unsalted SHA-256
  of `SECRET_KEY` to **PBKDF2-HMAC-SHA256** (`app/services/live_connectors.py`).
- Consequence: connector/LLM credentials encrypted under the OLD scheme can no
  longer be decrypted and must be **re-entered** after upgrade. If a pre-existing
  production deployment has stored BYOK keys, plan for re-entry (there is no
  automatic re-encryption path — the old key material is not recoverable by
  design). New installs are unaffected.

## 4. Production configuration (fail-fast — the app refuses to boot otherwise)
- `SECRET_KEY` (≥16 chars) and a unique `ADMIN_SECRET` are required outside DEV_MODE.
- `DATABASE_URL` must be **PostgreSQL** in a production environment — the app now
  refuses to boot on SQLite in production (SQLite has no row-level security).
- The app must connect as the **non-owner** `kaeos_app` role (set
  `KAEOS_OWNER_DB_URL` for the owner/maintenance connection). At startup
  `assert_rls_effective()` verifies the app role is not a table owner and that
  `tenant_isolation` policies exist — it **fails closed in production** if RLS is
  inert. Run `scripts/verify_rls.py` as an additional gate.
- `ALLOW_SIMULATED_LLM` must stay **false** in production. When no LLM provider is
  reachable, governance gates (compliance/fairness/debate/HITL) now **fail closed**
  (deny / route to human) instead of auto-approving on simulated output.
- `SEED_DEMO_DATA=false` for a real deployment so dashboards reflect only
  genuinely ingested data (not the fictional `tenant_acme` demo dataset).

## 5. Dependencies
- `starlette==0.38.6` is now pinned (fastapi 0.115 needs <0.41; an unpinned
  resolve pulls a newer Starlette that breaks route imports).
- Build/run on the **pinned Python version used by the Docker image** (3.11/3.12).
  `psycopg2-binary` (used by Alembic's sync URL) has no wheel for Python 3.14 and
  will try to build from source (needs `pg_config`). Do not run the backend on a
  bleeding-edge Python outside the container.

## 6. New integrity tooling (wire into CI)
- `python -m scripts.check_migration_drift` — fails if migrations can't build the
  full model schema (guards against schema/migration drift).
- `python -m scripts.check_tenant_integrity --strict` — fails if any row carries a
  `tenant_id` not present in the `tenants` registry (orphan detection; stands in
  for DB-level tenant FKs, which remain a follow-up).

## Still outstanding (NOT done in this pass)
- **RLS has not been verified on a running Postgres** in this work — the dev/CI
  machine has no Docker/Postgres. Verify on a real Postgres before onboarding a
  real client: boot the stack on Postgres, confirm `assert_rls_effective` passes,
  run `scripts/verify_rls.py`, and run the full E2E suite against Postgres.
- **Full DB-level foreign keys** from tenant tables to `tenants` (needs an
  orphan-cleanup migration).
