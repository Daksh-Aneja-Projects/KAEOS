# KAEOS Operational Runbook

## 0a. Fresh Database Bootstrap (verified 2026-07-17 on a clean Postgres volume)

Order matters, and both steps run as the OWNER role (`kaeos`):

1. **First backend boot runs `init_db()`** - creates the full schema and enables the
   pgvector extension automatically (the app's maintenance connection uses
   `KAEOS_OWNER_DB_URL`).
2. **`alembic upgrade head`** - installs the RLS policies on every tenant table and
   creates the non-owner `kaeos_app` role. Alembic follows `DATABASE_URL`, which in the
   container points at `kaeos_app` (correct for the app, wrong for DDL) - override for
   this one command:
   ```bash
   docker compose exec backend sh -c 'DATABASE_URL="$KAEOS_OWNER_DB_URL" alembic upgrade head'
   ```
   The migration chain is state-aware (checks before adding), so it is safe on both
   fresh and existing databases, before or after `create_all`.
3. **Prove tenant isolation** after any deploy:
   ```bash
   DATABASE_URL=<kaeos_app url> KAEOS_OWNER_DB_URL=<owner url> python scripts/verify_rls.py
   # → RLS ENFORCED
   ```
   If it reports the connected role OWNS the tables, the app is connecting as the owner
   and every policy is silently inert - fix the DATABASE_URL before going further.

## 0b. Known Version Pins (do not "upgrade past" these without re-verifying)

- **`bcrypt` must stay <5** (pinned 4.2.1). bcrypt 5 rejects passlib 1.7.4's 72-byte
  self-test, which breaks EVERY password verify - the symptom is
  "Invalid email or password" for all users while the hashes in the DB are fine.
- **Postgres image must be `pgvector/pgvector:pg16`** - plain Postgres lacks the
  `vector` type.
- **Vite bakes `VITE_API_BASE` at BUILD time.** It is a compose *build arg* (see
  frontend service), not runtime environment - and it must be a URL the user's
  BROWSER can reach (`http://localhost:8001/api/v1` or the public API host), never
  the Docker-internal `backend:8001`. Symptom of getting this wrong: login page
  renders but every request says "Failed to fetch".

## 0. Staging / Production Prerequisites (verified 2026-07-16)

- **Postgres must be the `pgvector/pgvector:pg16` image** (compose files already use it) and the
  database needs `CREATE EXTENSION IF NOT EXISTS vector;` before first boot - the semantic-memory
  tables use the `vector` type and schema creation fails on plain Postgres. Full schema creation
  was verified against a real pgvector container: 173 tables, zero errors.
- **Redis is required in staging/production.** Without it the HITL manager falls back to a
  single-process memory store (fine for dev, wrong for multi-worker). The Redis path was verified
  live: Gate-3 pause -> `kaeos:hitl:<execution_id>` key -> approve -> resume.
- **Set `ENVIRONMENT=staging` (or `production`).** The backend REFUSES TO BOOT with `DEV_MODE=true`
  unless ENVIRONMENT is explicitly a known-local value (development/dev/local/test/testing/ci) -
  DEV_MODE disables auth and tenant isolation, so an unset or non-local ENVIRONMENT fails closed.
- Local LLM default is `ollama/qwen2.5-coder:7b` (fits a 6GB GPU). `phi4-mini` remains available
  as the weak-model BYOK demo: its probed ceiling routes decisions to humans.

## 1. Incident Response

### 1.1 Backend Returns 500 (Internal Server Error)
- **Symptom**: Frontend displays error alerts, or API returns 500 status.
- **Action**: 
  1. SSH into the backend server / container.
  2. Check the logs: `docker logs kaeos-backend-1 --tail 100`
  3. Look for `httpx.ReadTimeout` which indicates the local Ollama LLM is overwhelmed.
  4. If database related, check `docker logs kaeos-postgres-1`.

### 1.2 LLM (Ollama) Timeouts
- **Symptom**: Agents stuck in PENDING, blueprints fail to compile, or 504 Gateway Timeouts.
- **Action**:
  1. Restart Ollama service: `systemctl restart ollama` or restart the Docker container.
  2. Verify the model is loaded in memory: `ollama run phi4-mini`.
  3. Clear the HITL queue if tasks were interrupted (see 1.4).

### 1.3 Database Connection Refused
- **Symptom**: Backend fails to start with `asyncpg.exceptions.ConnectionDoesNotExistError`.
- **Action**:
  1. Verify Postgres is running: `docker ps | grep postgres`.
  2. Check healthcheck status in `docker ps`.
  3. Ensure `DATABASE_URL` in `.env` is correctly pointing to the Postgres host and port.

### 1.4 HITL (Human-In-The-Loop) Queue Stuck
- **Symptom**: Tasks remain in `PENDING` state on the frontend despite being approved.
- **Action**:
  1. The HITL manager uses Redis for temporary state.
  2. Connect to Redis: `docker exec -it kaeos-redis-1 redis-cli`.
  3. Check keys: `KEYS kaeos:hitl:*` - the prefix is `kaeos:hitl:` (`_HITL_KEY_PREFIX` in
     `app/services/hitl_manager.py`). Plain `KEYS hitl:*` matches nothing.
  4. If a key is orphaned, it expires on its TTL (24h). Delete manually with `DEL kaeos:hitl:<exec_id>`.
  5. Note there are **two** HITL systems and they are not interchangeable:
     - `/skills/hitl/*` - DB-backed, reads `SkillExecution` rows (status `PENDING_HITL`).
     - `/hitl/*` and `/hr/hitl/*` - `hitl_manager`, Redis-backed, fed by agent-runtime gate 7.
     Approving in one does not resolve the other. Check which system created the item.

### 1.5 Everything Suddenly Routes to Human Approval

- **Symptom**: Skills that used to run autonomously now all return `PENDING_HITL`. No code changed.
- **Cause**: The tenant's model was probed and earned a low capability ceiling. This is **working as
  designed** - a model that fails the probe is not trusted with autonomy.
- **Action**:
  1. `GET /api/v1/config/llm-routing` and read `capability_profile.tier_ceiling` for
     `TIER_1_COMPLEX`. Anything below **0.82** caps confidence under the HITL threshold, so every
     decision gates.
  2. Check `capability_profile.recommendation` and `errors` for why it scored low.
  3. Options:
     - Point the tier at a stronger model (`POST /config/llm-routing`) - this auto-invalidates the
       stale profile - then re-probe: `POST /config/llm-routing/TIER_1_COMPLEX/probe`.
     - Or `DELETE /config/llm-routing/TIER_1_COMPLEX` to fall back to platform defaults.
  4. An **unprobed** tier imposes no cap. If you want to lift the cap without changing models,
     changing the model name and back clears the profile.
  5. Known: `phi4-mini` probes at ~0.70 (fails strict instruction-following). It is fine for
     `TIER_2_STANDARD`/`TIER_3_FAST`, not for the reasoning tier in an autonomous deployment.

### 1.6 A Connector Reports `ok: false`

- **Symptom**: `POST /connectors/{id}/test` returns 200 with `{"ok": false, "detail": ...}`.
- **Note**: This is correct behaviour, not an outage - adapters never raise on bad credentials.
- **Action**:
  1. Read `detail`; it carries the vendor's own status code and message.
  2. `GET /connectors/providers` lists every supported adapter and its `required_config` keys.
     A missing required key is rejected at `PUT /credentials` time with a 400.
  3. If secrets were stored before `SECRET_KEY` changed, decryption fails - re-enter the credentials.
     Rotating `SECRET_KEY` invalidates **all** stored connector secrets and BYOK model keys.

## 2. Staging & Production Deployment

### 2.1 Deploying Staging
```bash
docker compose -f docker-compose.staging.yml up --build -d
```
- Staging enforces Resource Limits (CPU/Memory) to prevent Out of Memory (OOM) issues on shared nodes.

### 2.2 Database Backups
- **Create Backup**:
  ```bash
  docker exec -t kaeos-postgres-1 pg_dumpall -c -U kaeos > dump_`date +%d-%m-%Y"_"%H_%M_%S`.sql
  ```
- **Restore Backup**:
  ```bash
  cat dump_...sql | docker exec -i kaeos-postgres-1 psql -U kaeos
  ```

## 3. Local LLM Management
- KAEOS uses `phi4-mini` via Ollama.
- To preload the model on boot, ensure the Ollama initialization script runs `ollama pull phi4-mini`.
