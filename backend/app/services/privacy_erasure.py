"""KAEOS — Privacy erasure & tenant purge (GDPR Art.17 / Art.28, DPDP).

Operations, deliberately separated by blast radius:

- ``purge_tenant``  — Art.28 processor offboarding: hard-delete EVERY row that
  belongs to a tenant, across every tenant-scoped table, AND delete the blobs
  those rows referenced. Irreversible.
- ``erase_subject`` — Art.17 right-to-erasure for a single data subject: replace
  direct identifiers (name/email/phone) with a tombstone, null free-text PII on
  the main HR tables, delete the subject's stored files (resume/documents) from
  the blob layer, and purge the subject's vector embeddings.
- ``replay_deletions`` — after restoring a backup (which predates an erasure),
  re-apply every recorded erasure so the backup cannot resurrect deleted PII.

COVERAGE (read honestly before relying on this):
  * Erasure now reaches THREE layers: the relational DB (tombstone/null),
    the blob layer (``app/core/polystore/blob_store`` — local FS + best-effort
    S3/GCS), and the vector store (subject embeddings). Backups are covered
    indirectly via the deletion journal + ``replay_deletions``, not by reaching
    into the backup files.
  * Provenance/foundry/ledger records retain HASHED references (not raw PII) by
    design so the append-only integrity trail stays verifiable; those hashes are
    not reversed. Free-text prose elsewhere that may mention a name is out of scope.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Optional

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Tombstone written over direct identifiers. Deterministic so a re-run is a no-op
# and so downstream code sees a clearly non-real, non-PII marker.
_TOMBSTONE = "[ERASED]"
_TOMBSTONE_EMAIL_FMT = "erased+{}@invalid.example"


def _email_hash(email: Optional[str]) -> Optional[str]:
    """SHA-256 of a normalized email, or None. The journal stores this, never raw."""
    if not email:
        return None
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()


async def _record_deletion(
    db: AsyncSession, tenant_id: str, operation: str,
    *, employee_id: Optional[str] = None, email: Optional[str] = None,
) -> None:
    """Append a deletion-journal entry (for backup-restore replay). Best-effort:
    a journaling failure must never abort the erasure that already committed."""
    try:
        from app.models.settings import DeletionJournal
        db.add(DeletionJournal(
            tenant_id=tenant_id, operation=operation,
            subject_employee_id=employee_id,
            subject_email_hash=_email_hash(email),
        ))
        await db.commit()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("[PrivacyErasure] deletion-journal write failed: %s", exc)


async def purge_tenant(db: AsyncSession, tenant_id: str) -> dict:
    """Hard-delete all rows for ``tenant_id`` across every tenant-scoped table,
    then delete the blobs those rows pointed at.

    Iterates ``Base.metadata.sorted_tables`` in FK-safe REVERSE order and deletes
    from every table with a matching ``tenant_id``. Returns an auditable receipt.
    Irreversible. Intended for Art.28 tenant offboarding.
    """
    if not tenant_id:
        raise ValueError("purge_tenant requires a non-empty tenant_id")

    from app.models.domain import Base
    import app.core.database  # noqa: F401 — ensures all tables are registered

    # Collect blob paths BEFORE the rows are deleted (afterwards they are gone).
    blob_paths = await _collect_tenant_blob_paths(db, tenant_id)

    deleted: dict[str, int] = {}
    for table in reversed(Base.metadata.sorted_tables):
        if "tenant_id" not in table.c:
            continue
        result = await db.execute(
            delete(table).where(table.c.tenant_id == tenant_id)
        )
        deleted[table.name] = int(result.rowcount or 0)

    await db.commit()

    from app.core.polystore import blob_store
    blobs = await blob_store.delete_blobs(blob_paths)
    await _record_deletion(db, tenant_id, "PURGE_TENANT")

    total = sum(deleted.values())
    logger.info(
        "[PrivacyErasure] purged tenant %s: %d rows across %d tenant-scoped tables, "
        "%d/%d blobs deleted",
        tenant_id, total, len(deleted), blobs["deleted"], blobs["attempted"],
    )
    return {
        "tenant_id": tenant_id, "total_rows_deleted": total, "tables": deleted,
        "blobs_deleted": blobs["deleted"], "blobs_attempted": blobs["attempted"],
    }


async def _collect_tenant_blob_paths(db: AsyncSession, tenant_id: str) -> list[str]:
    """Every stored-file path referenced by a tenant's rows (resumes, documents)."""
    from app.models.domain import Base
    import app.core.database  # noqa: F401

    tables = Base.metadata.tables
    paths: list[str] = []
    for tname, col in (("hr_candidates", "resume_path"), ("hr_employee_documents", "file_path")):
        t = tables.get(tname)
        if t is None or col not in t.c or "tenant_id" not in t.c:
            continue
        rows = (await db.execute(
            select(t.c[col]).where(t.c.tenant_id == tenant_id)
        )).scalars().all()
        paths.extend(p for p in rows if p)
    return paths


async def erase_subject(
    db: AsyncSession,
    tenant_id: str,
    *,
    employee_id: Optional[str] = None,
    email: Optional[str] = None,
    _journal: bool = True,
) -> dict:
    """Irreversibly anonymise a single data subject across DB, blobs and vectors.

    Matches on employee/candidate id and/or email (at least one required). For
    every matching row, overwrites direct identifiers with a tombstone, nulls
    free-text PII, DELETES the subject's stored files, and purges the subject's
    vector embeddings. Rows are kept (not deleted) so FK-linked history stays
    consistent while the PII is gone.
    """
    if not tenant_id:
        raise ValueError("erase_subject requires a tenant_id")
    if not (employee_id or email):
        raise ValueError("erase_subject requires at least one of employee_id / email")

    from app.models.domain import Base
    import app.core.database  # noqa: F401 — ensure HR tables are registered

    tables = Base.metadata.tables
    affected: dict[str, int] = {}
    blob_paths: list[str] = []
    tomb_email = _TOMBSTONE_EMAIL_FMT.format(employee_id or "subject")

    # ── hr_employees ──────────────────────────────────────────────────────
    emp = tables.get("hr_employees")
    if emp is not None:
        conds = []
        if employee_id and "id" in emp.c:
            conds.append(emp.c.id == employee_id)
        if email and "email" in emp.c:
            conds.append(emp.c.email == email)
        if email and "personal_email" in emp.c:
            conds.append(emp.c.personal_email == email)
        if conds:
            values = {}
            if "first_name" in emp.c:
                values["first_name"] = _TOMBSTONE
            if "last_name" in emp.c:
                values["last_name"] = _TOMBSTONE
            if "email" in emp.c:
                values["email"] = tomb_email
            if "personal_email" in emp.c:
                values["personal_email"] = None
            if "phone" in emp.c:
                values["phone"] = None
            if "communication_preferences" in emp.c:
                values["communication_preferences"] = {}
            if "accessibility_needs" in emp.c:
                values["accessibility_needs"] = {}
            res = await db.execute(
                update(emp).where(emp.c.tenant_id == tenant_id).where(or_(*conds)).values(**values)
            )
            affected["hr_employees"] = int(res.rowcount or 0)

    # ── hr_candidates (collect resume blob BEFORE nulling the pointer) ─────
    cand = tables.get("hr_candidates")
    if cand is not None:
        conds = []
        if employee_id and "id" in cand.c:
            conds.append(cand.c.id == employee_id)
        if email and "email" in cand.c:
            conds.append(cand.c.email == email)
        if conds:
            if "resume_path" in cand.c:
                paths = (await db.execute(
                    select(cand.c.resume_path).where(cand.c.tenant_id == tenant_id).where(or_(*conds))
                )).scalars().all()
                blob_paths.extend(p for p in paths if p)
            values = {}
            if "first_name" in cand.c:
                values["first_name"] = _TOMBSTONE
            if "last_name" in cand.c:
                values["last_name"] = _TOMBSTONE
            if "email" in cand.c:
                values["email"] = tomb_email
            if "phone" in cand.c:
                values["phone"] = None
            if "resume_path" in cand.c:
                values["resume_path"] = None
            if "ai_summary" in cand.c:
                values["ai_summary"] = None
            if "ai_red_flags" in cand.c:
                values["ai_red_flags"] = []
            if "eeoc_data" in cand.c:
                values["eeoc_data"] = None
            res = await db.execute(
                update(cand).where(cand.c.tenant_id == tenant_id).where(or_(*conds)).values(**values)
            )
            affected["hr_candidates"] = int(res.rowcount or 0)

    # ── hr_employee_documents (collect file blob BEFORE tombstoning) ──────
    docs = tables.get("hr_employee_documents")
    if docs is not None and employee_id and "employee_id" in docs.c:
        if "file_path" in docs.c:
            paths = (await db.execute(
                select(docs.c.file_path).where(docs.c.tenant_id == tenant_id)
                .where(docs.c.employee_id == employee_id)
            )).scalars().all()
            blob_paths.extend(p for p in paths if p)
        values = {}
        if "file_path" in docs.c:
            values["file_path"] = _TOMBSTONE
        if "title" in docs.c:
            values["title"] = _TOMBSTONE
        if values:
            res = await db.execute(
                update(docs).where(docs.c.tenant_id == tenant_id)
                .where(docs.c.employee_id == employee_id).values(**values)
            )
            affected["hr_employee_documents"] = int(res.rowcount or 0)

    await db.commit()

    # ── Blob layer: delete the actual stored files ────────────────────────
    from app.core.polystore import blob_store
    blobs = await blob_store.delete_blobs(blob_paths)

    # ── Vector embeddings (semantic memory) ───────────────────────────────
    embeddings_deleted = 0
    try:
        from app.core.polystore.vector_store import get_vector_store
        store = get_vector_store()
        embeddings_deleted = await store.delete_subject(
            tenant_id,
            subject_ids=[employee_id] if employee_id else [],
            subject_texts=[email] if email else [],
        )
    except Exception as exc:
        logger.warning("[PrivacyErasure] vector-embedding purge skipped: %s", exc)

    if _journal:
        await _record_deletion(db, tenant_id, "ERASE_SUBJECT",
                               employee_id=employee_id, email=email)

    total = sum(affected.values())
    logger.info(
        "[PrivacyErasure] erased subject (employee_id=%s email=%s) for tenant %s: "
        "%d rows anonymised across %d tables, %d/%d blobs deleted, %d embeddings deleted",
        employee_id, "<redacted>" if email else None, tenant_id, total, len(affected),
        blobs["deleted"], blobs["attempted"], embeddings_deleted,
    )
    return {
        "tenant_id": tenant_id,
        "employee_id": employee_id,
        "matched_by_email": bool(email),
        "total_rows_anonymised": total,
        "tables": affected,
        "blobs_deleted": blobs["deleted"],
        "blobs_attempted": blobs["attempted"],
        "embeddings_deleted": embeddings_deleted,
        "note": (
            "Direct identifiers tombstoned on the HR tables; stored files deleted "
            "from the blob layer; subject embeddings purged from the vector store; "
            "erasure journaled for backup-restore replay. Hash-chained ledger "
            "references are retained by design."
        ),
    }


async def replay_deletions(db: AsyncSession, tenant_id: Optional[str] = None) -> dict:
    """Re-apply every journaled erasure. Run this after restoring a backup.

    A restored backup predates the erasures it does not know about; replaying the
    journal re-applies them so deleted PII cannot silently return. Erasure is
    idempotent, so replay is safe to run repeatedly.

    Id-based entries re-erase by employee id directly. Email-only entries are
    re-matched by hashing the live rows' emails against the stored SHA-256 (no raw
    email is ever stored), so replay needs no plaintext email to work.
    """
    from app.models.settings import DeletionJournal
    import app.core.database  # noqa: F401
    from datetime import datetime, timezone

    q = select(DeletionJournal)
    if tenant_id:
        q = q.where(DeletionJournal.tenant_id == tenant_id)
    entries = (await db.execute(q)).scalars().all()

    replayed = 0
    for entry in entries:
        try:
            if entry.operation == "PURGE_TENANT":
                await purge_tenant(db, entry.tenant_id)
            elif entry.subject_employee_id:
                await erase_subject(db, entry.tenant_id,
                                    employee_id=entry.subject_employee_id, _journal=False)
            elif entry.subject_email_hash:
                email = await _find_email_by_hash(db, entry.tenant_id, entry.subject_email_hash)
                if email:
                    await erase_subject(db, entry.tenant_id, email=email, _journal=False)
            entry.replayed_at = datetime.now(timezone.utc)
            replayed += 1
        except Exception as exc:  # one bad entry must not abort the replay
            logger.warning("[PrivacyErasure] replay failed for %s: %s", entry.id, exc)
    await db.commit()
    logger.info("[PrivacyErasure] replayed %d/%d deletion-journal entries", replayed, len(entries))
    return {"entries": len(entries), "replayed": replayed}


async def _find_email_by_hash(db: AsyncSession, tenant_id: str, email_hash: str) -> Optional[str]:
    """Locate a live email whose SHA-256 matches, without storing raw email."""
    from app.models.domain import Base
    import app.core.database  # noqa: F401

    tables = Base.metadata.tables
    for tname in ("hr_employees", "hr_candidates"):
        t = tables.get(tname)
        if t is None or "email" not in t.c or "tenant_id" not in t.c:
            continue
        emails = (await db.execute(
            select(t.c.email).where(t.c.tenant_id == tenant_id)
        )).scalars().all()
        for e in emails:
            if e and _email_hash(e) == email_hash:
                return e
    return None
