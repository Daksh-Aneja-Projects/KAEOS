#!/bin/bash
set -e

# Migrations perform DDL (CREATE TABLE, indexes, RLS policies) which the
# non-owner app role (kaeos_app in DATABASE_URL) is deliberately not allowed to
# do. Run Alembic against the OWNER connection when one is configured, scoping
# the override to just this command so the server below still starts as the
# non-owner app role. Falls back to DATABASE_URL for SQLite / non-RLS setups.
echo "Running production migrations (as owner role)..."
DATABASE_URL="${KAEOS_OWNER_DB_URL:-$DATABASE_URL}" alembic upgrade head

# Prometheus multiprocess: with -w4 each worker has its own registry, so /metrics
# would serve only the scraped worker (~1/4 of reality) unless the workers share
# a directory. gunicorn.conf.py (auto-loaded from CWD, passed explicitly here)
# resets this dir on boot and marks dead workers so the endpoint aggregates
# correctly. EXPOSE_METRICS publishes the /metrics endpoint (off by default).
export PROMETHEUS_MULTIPROC_DIR="${PROMETHEUS_MULTIPROC_DIR:-/tmp/kaeos-metrics}"
export EXPOSE_METRICS="${EXPOSE_METRICS:-true}"

echo "Starting Gunicorn server (as non-owner app role)..."
exec gunicorn app.main:app -c gunicorn.conf.py -w "${GUNICORN_WORKERS:-4}" -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8001
