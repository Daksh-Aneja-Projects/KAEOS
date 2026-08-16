"""KAEOS — Privacy erasure & tenant purge (GDPR Art.17 / Art.28, DPDP).

Operations, deliberately separated by blast radius:

- ``purge_tenant``  — Art.28 processor offboarding: hard-delete EVERY row that
  belongs to a tenant, across every tenant-scoped table, AND delete the blobs
  those rows referenced. Irreversible.
- ``erase_subject`` — Art.17 right-to-erasure for a single data subject: replace
  direct identifiers (name/email/phone) with a tombstone, null free-text PII
  across the HR, sales, finance, healthcare and lending tables, delete the
  subject's stored files (resume/documents) from the blob layer, and purge the
  subject's vector embeddings.
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
    for tname, col in (
        ("hr_candidates", "resume_path"),
        ("hr_employee_documents", "file_path"),
        ("leg_contracts", "document_path"),
        ("leg_court_filings", "document_path"),
    ):
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
    subject_ref: Optional[str] = None,
    _journal: bool = True,
) -> dict:
    """Irreversibly anonymise a single data subject across DB, blobs and vectors.

    Matches on employee/candidate id, email, and/or external subject ref (the
    lending applicant/borrower id or the healthcare patient ref) - at least one
    required. For every matching
    row, overwrites direct identifiers with a tombstone, nulls free-text PII,
    DELETES the subject's stored files, and purges the subject's vector
    embeddings. Rows are kept (not deleted) so FK-linked history stays consistent
    while the PII is gone.
    """
    if not tenant_id:
        raise ValueError("erase_subject requires a tenant_id")
    if not (employee_id or email or subject_ref):
        raise ValueError(
            "erase_subject requires at least one of employee_id / email / subject_ref")

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

    # ── Lending vertical: applicant/borrower direct identifiers ───────────
    # The subject in lending is keyed by the external applicant_ref. A caller
    # may pass it as subject_ref, or reuse employee_id as that ref.
    ref = subject_ref or employee_id
    if ref:
        apps = tables.get("lnd_loan_applications")
        app_ids: list[str] = []
        if apps is not None and "applicant_ref" in apps.c:
            app_ids = list((await db.execute(
                select(apps.c.id).where(apps.c.tenant_id == tenant_id)
                .where(apps.c.applicant_ref == ref)
            )).scalars().all())
            values = {}
            if "applicant_name" in apps.c:
                values["applicant_name"] = _TOMBSTONE
            if "applicant_ref" in apps.c:
                values["applicant_ref"] = None
            if app_ids and values:
                res = await db.execute(
                    update(apps).where(apps.c.tenant_id == tenant_id)
                    .where(apps.c.applicant_ref == ref).values(**values)
                )
                affected["lnd_loan_applications"] = int(res.rowcount or 0)

        # Serviced loans link to the application; cascade the borrower name.
        loans = tables.get("lnd_serviced_loans")
        loan_ids: list[str] = []
        if loans is not None and app_ids and "application_id" in loans.c:
            loan_ids = list((await db.execute(
                select(loans.c.id).where(loans.c.tenant_id == tenant_id)
                .where(loans.c.application_id.in_(app_ids))
            )).scalars().all())
            if "borrower_name" in loans.c and loan_ids:
                res = await db.execute(
                    update(loans).where(loans.c.tenant_id == tenant_id)
                    .where(loans.c.application_id.in_(app_ids))
                    .values(borrower_name=_TOMBSTONE)
                )
                affected["lnd_serviced_loans"] = int(res.rowcount or 0)

        # Collection cases carry a free-text contact log (phone/notes); clear it.
        cases = tables.get("lnd_collection_cases")
        if cases is not None and loan_ids and "serviced_loan_id" in cases.c \
                and "contact_log" in cases.c:
            res = await db.execute(
                update(cases).where(cases.c.tenant_id == tenant_id)
                .where(cases.c.serviced_loan_id.in_(loan_ids))
                .values(contact_log=[])
            )
            affected["lnd_collection_cases"] = int(res.rowcount or 0)

        # ── Healthcare: patient PHI keyed on the pseudonymous patient_ref ──────
        # patient_ref is NOT NULL on encounters/consents, so it is tombstoned
        # (not nulled). Disclosures link only by encounter_id, so they are matched
        # through this patient's encounters (collected before the tombstone lands).
        enc = tables.get("hlth_encounters")
        enc_ids: list[str] = []
        if enc is not None and "patient_ref" in enc.c:
            enc_ids = list((await db.execute(
                select(enc.c.id).where(enc.c.tenant_id == tenant_id)
                .where(enc.c.patient_ref == ref)
            )).scalars().all())
            if enc_ids:
                values = {"patient_ref": _TOMBSTONE}
                if "reason" in enc.c:
                    values["reason"] = None
                res = await db.execute(
                    update(enc).where(enc.c.tenant_id == tenant_id)
                    .where(enc.c.patient_ref == ref).values(**values)
                )
                affected["hlth_encounters"] = int(res.rowcount or 0)

        consent = tables.get("hlth_consent_records")
        if consent is not None and "patient_ref" in consent.c:
            res = await db.execute(
                update(consent).where(consent.c.tenant_id == tenant_id)
                .where(consent.c.patient_ref == ref).values(patient_ref=_TOMBSTONE)
            )
            if res.rowcount:
                affected["hlth_consent_records"] = int(res.rowcount)

        disc = tables.get("hlth_phi_disclosures")
        if disc is not None and enc_ids and "encounter_id" in disc.c:
            values = {}
            if "minimum_necessary_justification" in disc.c:
                values["minimum_necessary_justification"] = _TOMBSTONE
            if "recipient" in disc.c:
                values["recipient"] = _TOMBSTONE
            if values:
                res = await db.execute(
                    update(disc).where(disc.c.tenant_id == tenant_id)
                    .where(disc.c.encounter_id.in_(enc_ids)).values(**values)
                )
                affected["hlth_phi_disclosures"] = int(res.rowcount or 0)

    # ── Sales & Finance: external-person direct identifiers (email-matched) ────
    # Sales contacts/leads and finance vendor/customer master records hold external
    # persons' direct identifiers. Same tombstone contract as the HR tables.
    if email:
        # (table, name-cols -> tombstone, cols -> null); each applied only if present.
        for tname, name_cols, null_cols in (
            ("sls_contacts", ("first_name", "last_name"), ("phone",)),
            ("sls_leads", ("contact_name",), ("phone",)),
            ("fin_vendors", (),
             ("phone", "tax_id", "bank_routing_number", "bank_account_number", "primary_contact")),
            ("fin_customers", (), ("phone", "tax_id", "primary_contact")),
        ):
            t = tables.get(tname)
            if t is None or "email" not in t.c or "tenant_id" not in t.c:
                continue
            values: dict = {"email": tomb_email}
            for c in name_cols:
                if c in t.c:
                    values[c] = _TOMBSTONE
            for c in null_cols:
                if c in t.c:
                    values[c] = None
            res = await db.execute(
                update(t).where(t.c.tenant_id == tenant_id).where(t.c.email == email).values(**values)
            )
            if res.rowcount:
                affected[tname] = int(res.rowcount)

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
            "Direct identifiers tombstoned across the HR, sales, finance, healthcare "
            "and lending tables; stored files deleted "
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
    for tname in ("hr_employees", "hr_candidates",
                  "sls_contacts", "sls_leads", "fin_vendors", "fin_customers"):
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


if __name__ == "__main__":  # tiny schema self-check for the erasure targets.
    # The `if col in table.c` guards above fail OPEN: a renamed table/column
    # silently stops erasing that PII. Assert the columns erasure relies on still
    # exist, so a schema drift breaks loudly here instead of leaking quietly.
    import app.core.database  # noqa: F401 — register every table
    from app.models.domain import Base as _Base

    _t = _Base.metadata.tables
    _expected = {
        "sls_contacts": ("email", "first_name", "last_name", "phone"),
        "sls_leads": ("email", "contact_name", "phone"),
        "fin_vendors": ("email", "tax_id", "bank_routing_number"),
        "fin_customers": ("email", "tax_id"),
        "hlth_encounters": ("patient_ref", "reason"),
        "hlth_phi_disclosures": ("encounter_id", "minimum_necessary_justification", "recipient"),
        "hlth_consent_records": ("patient_ref",),
        "leg_contracts": ("document_path",),
        "leg_court_filings": ("document_path",),
    }
    for _name, _cols in _expected.items():
        assert _name in _t, f"erasure target table missing: {_name}"
        for _c in _cols:
            assert _c in _t[_name].c, f"{_name}.{_c} renamed; erasure now skips it"
    print("privacy_erasure schema self-check OK")
