"""Gunicorn config - Prometheus multiprocess aggregation.

Gunicorn auto-loads this file from the working directory (WORKDIR /app), so no
-c flag is strictly required, though start-prod.sh passes one to be explicit.

Under ``-w4`` each worker is its own process with its own prometheus registry.
Without a shared directory, /metrics serves only the ONE worker that handled the
scrape - every counter reads ~1/4 of reality and flaps between scrapes. Setting
PROMETHEUS_MULTIPROC_DIR makes prometheus_client write each metric to an mmap
file there; the /metrics endpoint (Instrumentator.expose, multiproc-aware) then
sums across workers. On worker death we must mark its files dead or its last
values linger forever.
"""
import os
import shutil

_MULTIPROC_DIR = os.environ.setdefault("PROMETHEUS_MULTIPROC_DIR", "/tmp/kaeos-metrics")


def on_starting(server):
    """Master boot: start from a clean multiproc dir so stale mmap files from a
    previous run (crash/redeploy) do not inflate counters after restart."""
    try:
        if os.path.isdir(_MULTIPROC_DIR):
            shutil.rmtree(_MULTIPROC_DIR)
        os.makedirs(_MULTIPROC_DIR, exist_ok=True)
    except Exception as e:  # never block startup on the metrics dir
        server.log.warning("[metrics] could not reset %s: %s", _MULTIPROC_DIR, e)


def child_exit(server, worker):
    """A worker died: mark its metric files dead so MultiProcessCollector stops
    counting them (otherwise a crashed worker's last values persist forever)."""
    try:
        from prometheus_client import multiprocess
        multiprocess.mark_process_dead(worker.pid)
    except Exception as e:
        server.log.warning("[metrics] mark_process_dead(%s) failed: %s", worker.pid, e)
