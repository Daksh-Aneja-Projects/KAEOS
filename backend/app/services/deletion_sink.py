"""KAEOS — DR-safe EXTERNAL deletion-journal sink.

The DB-backed ``DeletionJournal`` lives in the SAME database a restore wipes, so
a post-restore ``replay_deletions`` finds nothing to replay: the resurrected PII
and its journal row are wiped together. This append-only FILE sink lives OUTSIDE
the DB restore boundary — restoring the database does not touch it — so the
erasure record survives to drive a replay.

Entries are PII-free by construction: operation, tenant_id, employee_id,
sha256(email), timestamp. Same content as the DB journal row, never raw email.

ponytail: a local append-only file is the FLOOR. Object storage with WORM /
Object-Lock (S3 Object Lock, immutable/versioned bucket) is the upgrade when the
restore boundary also covers the local filesystem, or multi-node durability is
required. Swap ``_journal_path`` for an object-store client and keep the shape.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def _journal_path() -> Path:
    """Configurable via KAEOS_DELETION_JOURNAL_PATH; defaults to a repo ``data/``
    file that survives a DB restore."""
    env = os.getenv("KAEOS_DELETION_JOURNAL_PATH")
    if env:
        return Path(env)
    # <repo>/data/deletion_journal.log  (parents: services→app→backend→repo)
    return Path(__file__).resolve().parents[3] / "data" / "deletion_journal.log"


def append(entry: dict) -> None:
    """Append one JSON line. Best-effort: a missing/unwritable path is logged,
    never raised — journaling must not abort an erasure that already committed."""
    try:
        path = _journal_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, separators=(",", ":"), sort_keys=True) + "\n")
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("[DeletionSink] external journal append failed: %s", exc)


def read_all() -> list[dict]:
    """Read every journal line back. Missing file → empty; malformed lines skipped
    (never crash a replay on one bad line)."""
    entries: list[dict] = []
    try:
        path = _journal_path()
        if not path.exists():
            return entries
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except Exception:
                    continue
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("[DeletionSink] external journal read failed: %s", exc)
    return entries


if __name__ == "__main__":  # sink round-trip self-check
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        os.environ["KAEOS_DELETION_JOURNAL_PATH"] = str(Path(d) / "j.log")
        append({"operation": "ERASE_SUBJECT", "tenant_id": "t1",
                "employee_id": "e1", "email_hash": None, "ts": "2026-01-01T00:00:00Z"})
        append({"operation": "ERASE_SUBJECT", "tenant_id": "t1",
                "employee_id": None, "email_hash": "abc", "ts": "2026-01-01T00:00:01Z"})
        got = read_all()
        assert len(got) == 2, got
        assert got[0]["employee_id"] == "e1"
        assert got[1]["email_hash"] == "abc"
    # missing path degrades to empty, never raises
    os.environ["KAEOS_DELETION_JOURNAL_PATH"] = str(Path(tempfile.gettempdir()) / "does_not_exist_kaeos.log")
    assert read_all() == []
    print("deletion_sink self-check OK")
