"""KAEOS — Privacy erasure & tenant purge (GDPR Art.17 / Art.28, DPDP).

Two operations, deliberately separated by blast radius:

- ``purge_tenant``  — Art.28 processor offboarding: hard-delete EVERY row that
  belongs to a tenant, across every tenant-scoped table. Irreversible.
- ``erase_subject`` — Art.17 right-to-erasure for a single data subject: replace
  direct identifiers (name/email/phone) with a tombstone and null out free-text
  PII on the main HR tables, keeping referential integrity intact.

COVERAGE / LIMITS (read honestly before relying on this):
  * ``purge_tenant`` deletes rows only from tables that carry a ``tenant_id``
    column. Global/shared tables (no tenant_id) and anything stored OUTSIDE the
    relational DB (object storage for resumes/documents referenced by file_path,
    vector-store embeddings, external log sinks, backups) are NOT touched here.
  * ``erase_subject`` covers the primary HR PII tables (hr_employees,
    hr_candidates) and their directly-attached document rows. By design,
    provenance/foundry/ledger records retain HASHED references (not raw PII) so
    the hash-chained audit trail stays verifiable — those hashes are not reversed
    or deleted, which is the intended, compliant behaviour for an append-only
    integrity ledger. Free-text fields elsewhere that may contain a subject's
    name in prose are out of scope.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Tombstone written over direct identifiers. Deterministic so a re-run is a no-op
# and so downstream code sees a clearly non-real, non-PII marker.
_TOMBSTONE = "[ERASED]"
_TOMBSTONE_EMAIL_FMT = "erased+{}@invalid.example"


async def purge_tenant(db: AsyncSession, tenant_id: str) -> dict:
    """Hard-delete all rows for ``tenant_id`` across every tenant-scoped table.

    Iterates ``Base.metadata.sorted_tables`` in FK-safe REVERSE order (children
    before parents) and deletes from every table that has a ``tenant_id`` column
    where it matches. Returns ``{table_name: deleted_row_count}`` for tables that
    had a matching column (0 included), so the caller gets an auditable receipt.

    Irreversible. Intended for Art.28 tenant offboarding. Does NOT touch object
    storage, vector stores, or backups (see module docstring).
    """
    if not tenant_id:
        raise ValueError("purge_tenant requires a non-empty tenant_id")

    # Imported lazily so importing this module never triggers full model import
    # side effects; app.core.database already registers every model on Base.
    from app.models.domain import Base
    import app.core.database  # noqa: F401 — ensures all tables are registered

    deleted: dict[str, int] = {}
    # sorted_tables is parent→child (FK-safe for creation); reverse for deletion.
    for table in reversed(Base.metadata.sorted_tables):
        if "tenant_id" not in table.c:
            continue
        result = await db.execute(
            delete(table).where(table.c.tenant_id == tenant_id)
        )
        deleted[table.name] = int(result.rowcount or 0)

    await db.commit()
    total = sum(deleted.values())
    logger.info(
        "[PrivacyErasure] purged tenant %s: %d rows across %d tenant-scoped tables",
        tenant_id, total, len(deleted),
    )
    return {"tenant_id": tenant_id, "total_rows_deleted": total, "tables": deleted}


async def erase_subject(
    db: AsyncSession,
    tenant_id: str,
    *,
    employee_id: Optional[str] = None,
    email: Optional[str] = None,
) -> dict:
    """Irreversibly anonymise a single data subject on the main HR PII tables.

    Matches on employee/candidate id and/or email (at least one required) and,
    for every matching row, overwrites direct identifiers (first/last name,
    email, personal_email, phone) with a tombstone and nulls free-text PII
    (ai_summary, resume path, etc.). Rows are kept (not deleted) so FK-linked
    operational history stays consistent while the PII is gone.

    Returns a per-table affected-row count. See module docstring for the honest
    coverage boundary (provenance/foundry keep hashed references by design).
    """
    if not tenant_id:
        raise ValueError("erase_subject requires a tenant_id")
    if not (employee_id or email):
        raise ValueError("erase_subject requires at least one of employee_id / email")

    from app.models.domain import Base
    import app.core.database  # noqa: F401 — ensure HR tables are registered

    tables = Base.metadata.tables
    affected: dict[str, int] = {}
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
            from sqlalchemy import or_
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
                update(emp)
                .where(emp.c.tenant_id == tenant_id)
                .where(or_(*conds))
                .values(**values)
            )
            affected["hr_employees"] = int(res.rowcount or 0)

    # ── hr_candidates ─────────────────────────────────────────────────────
    cand = tables.get("hr_candidates")
    if cand is not None:
        conds = []
        if employee_id and "id" in cand.c:
            conds.append(cand.c.id == employee_id)
        if email and "email" in cand.c:
            conds.append(cand.c.email == email)
        if conds:
            from sqlalchemy import or_
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
                update(cand)
                .where(cand.c.tenant_id == tenant_id)
                .where(or_(*conds))
                .values(**values)
            )
            affected["hr_candidates"] = int(res.rowcount or 0)

    # ── hr_employee_documents (attached PII by employee_id) ───────────────
    # These reference file_path blobs in object storage; we null the DB pointer
    # (the file itself must be deleted by the storage layer — out of scope here).
    docs = tables.get("hr_employee_documents")
    if docs is not None and employee_id and "employee_id" in docs.c:
        values = {}
        if "file_path" in docs.c:
            values["file_path"] = _TOMBSTONE
        if "title" in docs.c:
            values["title"] = _TOMBSTONE
        if values:
            res = await db.execute(
                update(docs)
                .where(docs.c.tenant_id == tenant_id)
                .where(docs.c.employee_id == employee_id)
                .values(**values)
            )
            affected["hr_employee_documents"] = int(res.rowcount or 0)

    await db.commit()
    total = sum(affected.values())
    logger.info(
        "[PrivacyErasure] erased subject (employee_id=%s email=%s) for tenant %s: "
        "%d rows anonymised across %d tables",
        employee_id, "<redacted>" if email else None, tenant_id, total, len(affected),
    )
    return {
        "tenant_id": tenant_id,
        "employee_id": employee_id,
        "matched_by_email": bool(email),
        "total_rows_anonymised": total,
        "tables": affected,
        "note": (
            "Direct identifiers tombstoned on main HR tables. Object-storage blobs "
            "(resume/document files), vector embeddings, and hash-chained ledger "
            "references are retained by design; delete those via their own layers."
        ),
    }
