#!/bin/bash
set -e

echo "Running production migrations..."
alembic upgrade head

echo "Starting Gunicorn server..."
exec gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8001
