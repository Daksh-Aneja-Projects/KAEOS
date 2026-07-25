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
5. Sanity-check: `curl http://localhost:8001/health` and log in to the frontend.

Note: dumps taken as the `kaeos` owner include grants for the `kaeos_app` role; that role exists in the same cluster (it lives in the `pgdata` volume, not in the dump). If you restore into a brand-new cluster, run the DB bootstrap (migrations + role setup) first so `kaeos_app` exists.

## 3. Secrets hygiene

Where the secrets live:

| Secret | Consumed by | Defined in |
|---|---|---|
| `POSTGRES_PASSWORD` | Postgres superuser `kaeos`; also embedded in `KAEOS_OWNER_DB_URL` | `docker-compose.yml` (env override, dev default `kaeos_dev_2026`), `.env` |
| `KAEOS_APP_DB_PASSWORD` | App role `kaeos_app` via `DATABASE_URL` | `docker-compose.yml` (env override, dev default `kaeos_app_dev`), `.env` |
| `SECRET_KEY` | FastAPI JWT signing | `.env` (loaded via `env_file` in compose) |
| `GRAFANA_ADMIN_PASSWORD` | Grafana admin | `docker-compose.yml` env override |

Rotation guidance:

- Rotate on a schedule (quarterly is a reasonable default) and immediately after any suspected exposure or team member departure.
- `POSTGRES_PASSWORD`: set the new value in `.env`, then apply it inside Postgres before restarting the stack: `docker exec -it kaeos-postgres-1 psql -U kaeos -c "ALTER USER kaeos WITH PASSWORD 'newvalue';"`, then `docker compose up -d` so the backend picks up the new `KAEOS_OWNER_DB_URL`. Changing only the env var does NOT change the password stored in the `pgdata` volume.
- `KAEOS_APP_DB_PASSWORD`: same pattern for the `kaeos_app` role: `ALTER USER kaeos_app WITH PASSWORD '...'`, update `.env`, restart backend.
- `SECRET_KEY`: rotating it invalidates all outstanding JWTs (all users must log in again). Generate with `python -c "import secrets; print(secrets.token_urlsafe(48))"`, update `.env`, restart backend. Prefer rotating during a maintenance window.
- Never commit `.env` (already gitignored). The dev defaults in `docker-compose.yml` are for local use only; any non-local deployment must override every `*_PASSWORD` and `SECRET_KEY` via environment or a secrets manager.
- Backups contain real data. Treat dump files with the same sensitivity as the live database: restrict filesystem access, encrypt at rest where possible.

## 4. Offsite copy

A backup on the same disk as the database does not survive disk loss. After each backup (or on a schedule), copy `backups/` to a second location:

- external drive or NAS: `robocopy D:\KAEOS\backups \\nas\kaeos-backups /MIR` (Windows) or `rsync -av backups/ user@host:/srv/kaeos-backups/` (Linux)
- cloud object storage: `aws s3 sync backups/ s3://your-bucket/kaeos-backups/` (or rclone for any provider), ideally to a bucket with versioning and restricted access
- keep at least the 3-2-1 baseline: 3 copies, 2 media, 1 offsite

Periodically test restores against a scratch database. A backup that has never been restored is not a backup.
