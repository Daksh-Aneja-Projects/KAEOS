"""KAEOS Postgres backup script.

Runs pg_dump (custom format) inside the Postgres container via docker exec
and writes a timestamped .dump file to the backups/ directory at the repo
root. Applies a simple age-based retention policy to old dumps.

Usage:
    python backend/scripts/backup_db.py
    python backend/scripts/backup_db.py --out-dir D:/backups --retention 30

Requires: Docker running with the kaeos-postgres-1 container up.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT_DIR = REPO_ROOT / "backups"
DEFAULT_CONTAINER = "kaeos-postgres-1"
DB_USER = "kaeos"
DB_NAME = "kaeos"
# A custom-format dump starts with the magic bytes "PGDMP". Anything smaller
# than this is definitely not a valid dump of a real schema.
MIN_PLAUSIBLE_SIZE = 1024


def fail(msg: str) -> "None":
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def check_docker(container: str) -> None:
    """Verify docker is reachable and the target container is running."""
    try:
        proc = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", container],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError:
        fail("docker CLI not found on PATH. Is Docker Desktop installed?")
    except subprocess.TimeoutExpired:
        fail("docker inspect timed out. Docker daemon may be unresponsive.")

    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        if "Cannot connect to the Docker daemon" in stderr or "docker daemon" in stderr.lower():
            fail("Docker daemon is not running. Start Docker Desktop and retry.")
        fail(
            f"container '{container}' not found or not inspectable: {stderr}\n"
            f"Hint: run 'docker compose up -d postgres' from the repo root."
        )
    if proc.stdout.strip() != "true":
        fail(f"container '{container}' exists but is not running. Start it with 'docker compose up -d postgres'.")


def run_backup(container: str, out_path: Path) -> None:
    """Stream pg_dump custom-format output from the container into out_path."""
    cmd = [
        "docker", "exec", container,
        "pg_dump", "-U", DB_USER, "-Fc", DB_NAME,
    ]
    print(f"Running: {' '.join(cmd)}")
    start = time.monotonic()
    with out_path.open("wb") as fh:
        proc = subprocess.run(cmd, stdout=fh, stderr=subprocess.PIPE, timeout=600)
    elapsed = time.monotonic() - start

    if proc.returncode != 0:
        stderr = proc.stderr.decode(errors="replace").strip()
        out_path.unlink(missing_ok=True)  # do not leave partial dumps behind
        fail(f"pg_dump failed (exit {proc.returncode}): {stderr}")

    # Verify the dump is real: non-trivial size and correct magic header.
    size = out_path.stat().st_size
    if size < MIN_PLAUSIBLE_SIZE:
        out_path.unlink(missing_ok=True)
        fail(f"dump file is suspiciously small ({size} bytes); removed it. Check pg_dump output.")
    with out_path.open("rb") as fh:
        magic = fh.read(5)
    if magic != b"PGDMP":
        out_path.unlink(missing_ok=True)
        fail("dump file does not start with the PGDMP magic header; removed it.")

    print(f"OK: wrote {out_path} ({size:,} bytes, {size / (1024 * 1024):.2f} MiB) in {elapsed:.1f}s")


def apply_retention(out_dir: Path, days: int, keep: Path) -> None:
    """Delete kaeos_*.dump files older than `days` days (never the one just written)."""
    if days <= 0:
        print("Retention disabled (retention <= 0); keeping all dumps.")
        return
    cutoff = datetime.now() - timedelta(days=days)
    deleted = 0
    for dump in sorted(out_dir.glob("kaeos_*.dump")):
        if dump.resolve() == keep.resolve():
            continue
        mtime = datetime.fromtimestamp(dump.stat().st_mtime)
        if mtime < cutoff:
            dump.unlink()
            print(f"Retention: deleted {dump.name} (modified {mtime:%Y-%m-%d %H:%M})")
            deleted += 1
    remaining = len(list(out_dir.glob("kaeos_*.dump")))
    print(f"Retention: {deleted} dump(s) deleted, {remaining} dump(s) retained (policy: {days} days).")


def main() -> None:
    parser = argparse.ArgumentParser(description="Back up the KAEOS Postgres database via docker exec + pg_dump.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR,
                        help=f"Directory to write dumps to (default: {DEFAULT_OUT_DIR})")
    parser.add_argument("--container", default=DEFAULT_CONTAINER,
                        help=f"Postgres container name (default: {DEFAULT_CONTAINER})")
    parser.add_argument("--retention", type=int, default=14, metavar="N",
                        help="Delete dumps older than N days (default: 14; 0 disables)")
    args = parser.parse_args()

    check_docker(args.container)

    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"kaeos_{stamp}.dump"

    run_backup(args.container, out_path)
    apply_retention(out_dir, args.retention, keep=out_path)

    print("\nBackup summary")
    print(f"  file:      {out_path}")
    print(f"  size:      {out_path.stat().st_size:,} bytes")
    print(f"  container: {args.container}")
    print(f"  database:  {DB_NAME} (user {DB_USER}, custom format)")
    print(f"  retention: {args.retention} days")


if __name__ == "__main__":
    main()
