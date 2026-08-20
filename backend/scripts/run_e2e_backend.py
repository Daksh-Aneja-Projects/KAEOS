"""Boot the backend for the local real-Ollama e2e lane.

Runs uvicorn on the KAEOS e2e port (8011) against a DEDICATED SQLite file, so
the lane always starts from a fresh, fully-seeded database. The long-lived dev kaeos.db cannot be used here: its
seeders are idempotent and skip already-seeded domains, so data added by newer
seed versions (serviced loans, work orders, GL journal entries) never lands in
it and every e2e assertion on that data would fail spuriously.

Usage: cd backend && python -m scripts.run_e2e_backend
Then:  KAEOS_TEST_URL=http://127.0.0.1:8011/api/v1 python -m pytest tests/e2e -q

The port is 8011, not 8001: 8001 belongs to another service on the maintainer's
machine, and booting this backend there takes it over silently - the suite then
passes or fails against a backend that is not the one under test. Override with
KAEOS_E2E_PORT if 8011 is busy, and point KAEOS_TEST_URL at the same port.
"""
import os
import pathlib
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

DB_PATH = BACKEND / "kaeos_e2e.db"
FRESH = os.environ.get("KAEOS_E2E_FRESH_DB", "1") != "0"

if FRESH and DB_PATH.exists():
    DB_PATH.unlink()
    print(f"[e2e-backend] removed stale {DB_PATH.name} (fresh seed on boot)")

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{DB_PATH.as_posix()}"

if __name__ == "__main__":
    import uvicorn
    # Lifespan does the rest on a fresh DB: create_all (DEV_MODE), domain seeds,
    # org-graph backbone, admin provisioning - the same path a dev boot takes.
    uvicorn.run("app.main:app", host="127.0.0.1",
                port=int(os.environ.get("KAEOS_E2E_PORT", "8011")),
                log_level="warning")
