"""KAEOS Postgres restore script.

Restores a custom-format pg_dump file into the running Postgres container via
docker exec + pg_restore with --clean --if-exists. This DROPS and recreates
objects in the target database, so it is destructive: it refuses to run
without the explicit --yes flag and always prints its plan first.

Usage:
    # Preflight only (prints the plan, touches nothing):
    python backend/scripts/restore_db.py backups/kaeos_20260725_120000.dump

    # Actually restore:
    python backend/scripts/restore_db.py backups/kaeos_20260725_120000.dump --yes
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

DEFAULT_CONTAINER = "kaeos-postgres-1"
DB_USER = "kaeos"
DB_NAME = "kaeos"


def fail(msg: str) -> "None":
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def check_docker(container: str) -> None:
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
        fail(f"container '{container}' not found or not inspectable: {stderr}")
    if proc.stdout.strip() != "true":
        fail(f"container '{container}' exists but is not running.")


def validate_dump(dump_path: Path) -> int:
    if not dump_path.is_file():
        fail(f"dump file not found: {dump_path}")
    size = dump_path.stat().st_size
    if size == 0:
        fail(f"dump file is empty: {dump_path}")
    with dump_path.open("rb") as fh:
        magic = fh.read(5)
    if magic != b"PGDMP":
        fail(f"{dump_path} does not look like a pg_dump custom-format file (missing PGDMP header).")
    return size


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Restore a KAEOS Postgres dump via docker exec + pg_restore (destructive)."
    )
    parser.add_argument("dump", type=Path, help="Path to the .dump file (pg_dump custom format)")
    parser.add_argument("--container", default=DEFAULT_CONTAINER,
                        help=f"Postgres container name (default: {DEFAULT_CONTAINER})")
    parser.add_argument("--yes", action="store_true",
                        help="Actually perform the restore. Without this flag only the plan is printed.")
    args = parser.parse_args()

    size = validate_dump(args.dump)
    check_docker(args.container)

    restore_cmd = [
        "docker", "exec", "-i", args.container,
        "pg_restore", "-U", DB_USER, "-d", DB_NAME, "--clean", "--if-exists",
    ]

    print("Restore plan")
    print(f"  dump file: {args.dump.resolve()} ({size:,} bytes)")
    print(f"  container: {args.container}")
    print(f"  database:  {DB_NAME} (user {DB_USER})")
    print(f"  command:   {' '.join(restore_cmd)}  < dump")
    print("  effect:    DROPS existing objects (--clean --if-exists) and recreates them from the dump.")
    print("  warning:   all data written to the database after this dump was taken WILL BE LOST.")

    if not args.yes:
        print("\nDry run only: no changes made. Re-run with --yes to perform the restore.")
        sys.exit(0)

    print("\nProceeding with restore...")
    with args.dump.open("rb") as fh:
        proc = subprocess.run(restore_cmd, stdin=fh, stderr=subprocess.PIPE, timeout=1800)

    stderr = proc.stderr.decode(errors="replace").strip()
    if proc.returncode != 0:
        # pg_restore exits non-zero on any error, including ignorable ones;
        # surface everything and let the operator judge.
        print(stderr, file=sys.stderr)
        fail(f"pg_restore exited with code {proc.returncode}. Review the errors above.")
    if stderr:
        print("pg_restore warnings:")
        print(stderr)
    print(f"OK: restore of {args.dump.name} into {DB_NAME} completed.")
    print("Next: restart the backend container so connection pools re-sync: docker compose restart backend")


if __name__ == "__main__":
    main()
