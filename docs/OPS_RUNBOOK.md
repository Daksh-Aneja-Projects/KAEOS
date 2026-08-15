# KAEOS Ops Runbook: Backup, Restore, Secrets

Operational procedures for the KAEOS PostgreSQL database (docker compose stack, service `postgres`, container `kaeos-postgres-1`, user `kaeos`, db `kaeos`).

## 1. Backup

### Manual backup

From the repo root, with the stack running:

```bash
python backend/scripts/backup_db.py
```

This runs `pg_dump -U kaeos -Fc kaeos` inside the container and writes a custom-format dump to `backups/kaeos_YYYYMMDD_HHMMSS.dump`. The script:

- verifies Docker and the container are up (clear error if not)
- verifies the dump is non-empty and has the `PGDMP` magic header
- deletes dumps older than 14 days (change with `--retention N`, `0` disables)

Options:

| Flag | Default | Purpose |
|---|---|---|
| `--out-dir` | `backups/` at repo root | Where dumps are written |
| `--container` | `kaeos-postgres-1` | Postgres container name |
| `--retention N` | `14` | Delete dumps older than N days |

`backups/` is gitignored: dumps contain tenant data and must never be committed.

### Scheduled backup: Windows Task Scheduler

Create a daily task (run from an elevated or normal prompt):

```
schtasks /Create /TN "KAEOS DB Backup" /SC DAILY /ST 02:00 ^
  /TR "\"C:\Path\To\python.exe\" D:\KAEOS\backend\scripts\backup_db.py"
```

Replace the python path with your interpreter (e.g. the repo venv: `D:\KAEOS\backend\.venv\Scripts\python.exe`). Verify with `schtasks /Query /TN "KAEOS DB Backup"` and test with `schtasks /Run /TN "KAEOS DB Backup"`.

### Scheduled backup: cron (Linux/macOS hosts)

```
0 2 * * * cd /path/to/KAEOS && /usr/bin/python3 backend/scripts/backup_db.py >> /var/log/kaeos-backup.log 2>&1
```

## 2. Restore

Restoring is destructive: it drops and recreates objects in the `kaeos` database. Any data written after the dump was taken is lost.

1. Stop the backend so nothing writes during the restore:
   ```bash
   docker compose stop backend
   ```
2. Preflight (prints the plan, touches nothing):
   ```bash
   python backend/scripts/restore_db.py backups/kaeos_YYYYMMDD_HHMMSS.dump
   ```
3. Execute:
   ```bash
   python backend/scripts/restore_db.py backups/kaeos_YYYYMMDD_HHMMSS.dump --yes
   ```
   This pipes the dump into `pg_restore -U kaeos -d kaeos --clean --if-exists` inside the container. `pg_restore` may report ignorable errors (e.g. dropping objects that do not exist); the script prints them for review.
4. Restart the backend:
   ```bash
   docker compose start backend
   ```
5. Sanity-check: `curl http://localhost:8001/status` (public, no auth: reports `version`,
   `uptime_seconds` and db/redis/llm reachability, and 503s while the database is unreachable),
   then `curl http://localhost:8001/health` for the backend-by-backend view, then log in to the
   frontend.
6. Confirm the schema is at the expected head: `alembic current` should report
   `0049_ops_work_orders`. A dump taken before an upgrade restores the *old* schema, so re-run
   `alembic upgrade head` as the owner role after restoring an older dump.

Note: dumps taken as the `kaeos` owner include grants for the `kaeos_app` role; that role exists in the same cluster (it lives in the `pgdata` volume, not in the dump). If you restore into a brand-new cluster, run the DB bootstrap (migrations + role setup) first so `kaeos_app` exists.

Note on the metrics series: `ts_metric_samples` is part of the database and is included in the dump like any other table. After a restore, the leader-guarded rollup resumes on its own schedule (`METRICS_ROLLUP_INTERVAL_MINUTES`, default 60) and writes are idempotent per bucket, so it will not duplicate the restored samples. It does not backfill the gap between the dump and the restore; that window stays empty rather than being filled with fabricated values.

## 3. Secrets hygiene

Where the secrets live:

| Secret | Consumed by | Defined in |
|---|---|---|
| `POSTGRES_PASSWORD` | Postgres superuser `kaeos`; also embedded in `KAEOS_OWNER_DB_URL` | `docker-compose.yml` (env override, dev default `kaeos_dev_2026`), `.env` |
| `KAEOS_APP_DB_PASSWORD` | App role `kaeos_app` via `DATABASE_URL` | `docker-compose.yml` (env override, dev default `kaeos_app_dev`), `.env` |
| `SECRET_KEY` | FastAPI JWT signing; also derives the at-rest key for stored connector/BYOK credentials | `.env` (loaded via `env_file` in compose) |
| `ADMIN_SECRET` | Guards the admin endpoints and the super-admin `/api/v1/ops/*` operator console (cross-tenant reads) | `.env` |
| `GRAFANA_ADMIN_PASSWORD` | Grafana admin | `docker-compose.yml` env override |

Rotation guidance:

- Rotate on a schedule (quarterly is a reasonable default) and immediately after any suspected exposure or team member departure.
- `POSTGRES_PASSWORD`: set the new value in `.env`, then apply it inside Postgres before restarting the stack: `docker exec -it kaeos-postgres-1 psql -U kaeos -c "ALTER USER kaeos WITH PASSWORD 'newvalue';"`, then `docker compose up -d` so the backend picks up the new `KAEOS_OWNER_DB_URL`. Changing only the env var does NOT change the password stored in the `pgdata` volume.
- `KAEOS_APP_DB_PASSWORD`: same pattern for the `kaeos_app` role: `ALTER USER kaeos_app WITH PASSWORD '...'`, update `.env`, restart backend.
- `SECRET_KEY`: rotating it invalidates all outstanding JWTs (all users must log in again) **and** every stored connector credential and BYOK model key, which must be re-entered afterwards. Generate with `python -c "import secrets; print(secrets.token_urlsafe(48))"`, update `.env`, restart backend. Prefer rotating during a maintenance window.
- `ADMIN_SECRET`: rotate it like any other operator credential; it is the gate on the super-admin `/api/v1/ops/*` console, which reads across tenants. Outside `DEV_MODE` the backend refuses to boot without it.
- Never commit `.env` (already gitignored). The dev defaults in `docker-compose.yml` are for local use only; any non-local deployment must override every `*_PASSWORD` and `SECRET_KEY` via environment or a secrets manager.
- Backups contain real data. Treat dump files with the same sensitivity as the live database: restrict filesystem access, encrypt at rest where possible.

## 4. Offsite copy

A backup on the same disk as the database does not survive disk loss. After each backup (or on a schedule), copy `backups/` to a second location:

- external drive or NAS: `robocopy D:\KAEOS\backups \\nas\kaeos-backups /MIR` (Windows) or `rsync -av backups/ user@host:/srv/kaeos-backups/` (Linux)
- cloud object storage: `aws s3 sync backups/ s3://your-bucket/kaeos-backups/` (or rclone for any provider), ideally to a bucket with versioning and restricted access
- keep at least the 3-2-1 baseline: 3 copies, 2 media, 1 offsite

Periodically test restores against a scratch database. A backup that has never been restored is not a backup.

## 5. Recovery objectives (RPO / RTO)

These are the platform's stated recovery targets. Backup cadence and rollback
procedure below are sized to meet them.

| Objective | Target | How it is met |
|---|---|---|
| **RPO** (max acceptable data loss) | **24 hours** | Nightly scheduled `backup_db.py` (section 1). Tighten to 1h with hourly WAL archiving / a managed-Postgres PITR tier when the workload warrants it. |
| **RTO** (max acceptable downtime) | **1 hour** | Restore drill below completes well inside this on a single-node deploy; the previous image tag stays pullable for an app-only rollback in minutes. |

Persistent state that MUST be in the backup set (see `docker-compose.prod.yml`
volumes): `pgdata` (the database), `applogs` (the `audit-fallback.jsonl`
tamper-evidence sink), and `appdata` (locally-stored blobs such as candidate
resumes, when object storage is not configured). Prefer S3/GCS blob URIs in
production so blob durability does not depend on a single node's volume.

### Restore drill (run quarterly)

An untested backup is not a backup. Once a quarter, prove the whole path end to
end against a scratch target, not the live database:

1. Stand up a scratch Postgres (a throwaway container is fine).
2. Restore the most recent backup into it with `python -m scripts.restore_db`.
3. Point a backend at it with `DATABASE_URL` and run `alembic current` — confirm
   it reports the expected head (currently `0049_ops_work_orders`).
4. Boot the backend and hit `/health`; spot-check one tenant's data.
5. Re-run journaled erasures against the restored DB
   (`POST /api/v1/privacy/erasure/replay`, section on erasure) so PII a caller
   deleted before the backup's cutoff cannot silently return after a restore.
6. Record the date and the measured restore time; if it exceeded the RTO, either
   raise the target or speed up the path.

## 6. Application rollback (bad release)

Distinct from a data restore: when a deploy ships a broken app but the database
is fine, roll the code back without touching data.

1. **Identify the last good image tag** (CI publishes one per merge to `main`;
   keep the previous few pullable).
2. **Roll back the code**: repoint the `backend` service to the previous image
   tag and redeploy (`docker compose -f docker-compose.prod.yml up -d backend`),
   or `helm rollback kaeos <previous-revision>` on the Helm path.
3. **Migrations are the one-way door.** If the bad release ran a migration, the
   older image will not boot against the newer schema. Options, in order of
   preference:
   - Prefer forward-fix (ship a corrective migration) over downgrading.
   - If you must downgrade, `alembic downgrade <target>` FIRST, then deploy the
     older image. Every migration `0045`+ has a tested `downgrade()`
     (`tests/test_prelaunch_fixes.py::test_recent_migrations_downgrade_and_reupgrade`),
     but a downgrade that drops a column is destructive - take a backup first.
4. **Verify**: `/health` is 200, `alembic current` is the expected head, and the
   symptom that triggered the rollback is gone.

## 7. Email deliverability (SPF / DKIM / DMARC)

KAEOS sends transactional and governance email (password reset, HITL approval
links, alerts) from the configured SMTP sender. Without sender authentication,
those land in spam or are spoofable. Configure all three on the sending domain
before enabling outbound email in production:

- **SPF**: publish a TXT record on the sending domain authorising your relay,
  e.g. `v=spf1 include:<your-esp-include> -all` (use `-all`, hard fail, once the
  list of senders is confirmed).
- **DKIM**: enable DKIM signing at the relay/ESP and publish the public key at
  `<selector>._domainkey.<domain>`. Verify a test message shows `dkim=pass`.
- **DMARC**: publish `_dmarc.<domain>` starting at
  `v=DMARC1; p=none; rua=mailto:dmarc@<domain>` to collect reports, then move to
  `p=quarantine` and finally `p=reject` once SPF and DKIM align cleanly.
- The notifier fails closed on a TLS-configured SMTP relay that cannot STARTTLS
  (it will not send governance mail in cleartext) unless
  `allow_plaintext_fallback` is set on the channel - keep that off in production.
