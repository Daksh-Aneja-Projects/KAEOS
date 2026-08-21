"""KAEOS — Privacy erasure & tenant purge (GDPR Art.17 / Art.28, DPDP).

Operations, deliberately separated by blast radius:

- ``purge_tenant``  — Art.28 processor offboarding: hard-delete EVERY row that
  belongs to a tenant, across every tenant-scoped table, AND delete the blobs
  those rows referenced. Irreversible.
- ``erase_subject`` — Art.17 right-to-erasure for a single data subject: replace
  direct identifiers (name/email/phone) with a tombstone, null free-text PII
  across the HR, sales, finance, support, engineering, operations, legal,
  healthcare and lending tables, delete the subject's stored files
  (resume/documents/receipts/evidence) from the blob layer, and purge the
  subject's vector embeddings. Rows under legal/litigation hold are preserved.
- ``replay_deletions`` — after restoring a backup (which predates an erasure),
  re-apply every recorded erasure so the backup cannot resurrect deleted PII.

COVERAGE (read honestly before relying on this):
  * Erasure now reaches THREE layers: the relational DB (tombstone/null),
    the blob layer (``app/core/polystore/blob_store`` — local FS + best-effort
    S3/GCS), and the vector store (subject embeddings). Backups are covered
    indirectly via the deletion journal + ``replay_deletions``, not by reaching
    into the backup files. The journal is written to TWO sinks: the DB table AND a
    DR-safe external file (``deletion_sink``) that survives a restore which wipes
    the DB table — replay it with ``replay_deletions_from_external``.
  * Erasure reaches CUSTOMER-authored support ticket content (description/comment
    body), procurement person fields (requested_by / receiver_name / vendor_name)
    and legal contract counterparty, in addition to the HR/sales/finance/
    healthcare/lending identifiers.
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

from app.services import deletion_sink

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


def _skip_held(stmt, table):
    """Exclude legal-hold rows from a destructive statement, when the table has
    the column. Legal/litigation hold OVERRIDES the right-to-erasure and tenant
    purge: held rows must survive (preservation beats Art.17). Fails CLOSED via
    ``IS NOT TRUE`` so NULL is treated as not-held and only True is skipped.

    Defensive: a no-op until an ``on_legal_hold`` boolean (default False) is added
    to the erasable tables (FLAGGED for the integrator).
    """
    if "on_legal_hold" in table.c:
        return stmt.where(table.c.on_legal_hold.isnot(True))
    return stmt


async def _record_deletion(
    db: AsyncSession, tenant_id: str, operation: str,
    *, employee_id: Optional[str] = None, email: Optional[str] = None,
) -> None:
    """Append a deletion-journal entry (for backup-restore replay). Best-effort:
    a journaling failure must never abort the erasure that already committed.

    Written to TWO places: the DB table (fast, tenant-scoped replay) AND a DR-safe
    EXTERNAL file sink that survives a restore which wipes the DB table (see
    ``deletion_sink`` / ``replay_deletions_from_external``)."""
    from datetime import datetime, timezone
    email_hash = _email_hash(email)

    # External sink FIRST: it is the record that survives a DB restore, so it must
    # not depend on the DB commit below succeeding. Already self-guarded (no raise).
    deletion_sink.append({
        "operation": operation,
        "tenant_id": tenant_id,
        "employee_id": employee_id,
        "email_hash": email_hash,
        "ts": datetime.now(timezone.utc).isoformat(),
    })

    try:
        from app.models.settings import DeletionJournal
        db.add(DeletionJournal(
            tenant_id=tenant_id, operation=operation,
            subject_employee_id=employee_id,
            subject_email_hash=email_hash,
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
            _skip_held(delete(table).where(table.c.tenant_id == tenant_id), table)
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
        ("leg_data_subject_requests", "evidence_path"),
        ("fin_invoices", "attachment_paths"),   # JSON list of scanned-invoice URIs
        ("fin_expense_items", "receipt_path"),
        ("fin_control_tests", "evidence_path"),
        ("fin_reports", "export_path"),
    ):
        t = tables.get(tname)
        if t is None or col not in t.c or "tenant_id" not in t.c:
            continue
        rows = (await db.execute(_skip_held(
            select(t.c[col]).where(t.c.tenant_id == tenant_id), t
        ))).scalars().all()
        for v in rows:
            if not v:
                continue
            if isinstance(v, (list, tuple)):    # JSON-list columns (attachment_paths)
                paths.extend(p for p in v if p)
            else:
                paths.append(v)
    return paths


async def _collect_subject_identity(
    db: AsyncSession, tables, tenant_id: str,
    employee_id: Optional[str], email: Optional[str],
) -> tuple[set[str], list[str], list[str]]:
    """Read the subject's identity BEFORE any tombstone overwrites its keys.

    Returns (subject_names, customer_ids, vendor_ids):
     - subject_names: the subject's human name(s), to reach free-text PERSON fields
       that carry a NAME rather than an id/email (procurement receiver, legal
       counterparty). No id/email key exists on those columns.
     - customer_ids / vendor_ids: the subject's finance-master ids, to reach rows
       keyed by those ids (support tickets by fin_customers.id, purchase orders by
       fin_vendors.id) AFTER the email key on the master has been tombstoned.

    Read-only: it must run before erase_subject writes anything, or the keys it
    matches on are already gone.
    """
    subject_names: set[str] = set()
    customer_ids: list[str] = []
    vendor_ids: list[str] = []

    def _add_name(*parts) -> None:
        full = " ".join(p.strip() for p in parts if p and p.strip())
        if full:
            subject_names.add(full)

    for _tn, _idc, _emailcs in (
        ("hr_employees", "id", ("email", "personal_email")),
        ("hr_candidates", "id", ("email",)),
    ):
        _t = tables.get(_tn)
        if _t is None or not {"first_name", "last_name"} <= set(_t.c.keys()):
            continue
        _conds = []
        if employee_id and _idc in _t.c:
            _conds.append(_t.c[_idc] == employee_id)
        for _ec in _emailcs:
            if email and _ec in _t.c:
                _conds.append(_t.c[_ec] == email)
        if not _conds:
            continue
        for _fn, _ln in (await db.execute(
            select(_t.c.first_name, _t.c.last_name)
            .where(_t.c.tenant_id == tenant_id).where(or_(*_conds))
        )).all():
            _add_name(_fn, _ln)

    if email:
        for _tn, _bucket in (("fin_customers", customer_ids), ("fin_vendors", vendor_ids)):
            _t = tables.get(_tn)
            if _t is None or "email" not in _t.c or "tenant_id" not in _t.c:
                continue
            _cols = [_t.c.id]
            if "name" in _t.c:
                _cols.append(_t.c.name)
            if "primary_contact" in _t.c:
                _cols.append(_t.c.primary_contact)
            for _row in (await db.execute(
                select(*_cols).where(_t.c.tenant_id == tenant_id).where(_t.c.email == email)
            )).all():
                _bucket.append(_row[0])
                for _v in _row[1:]:
                    _add_name(_v)

    return subject_names, customer_ids, vendor_ids


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
    # Per-subject unique tombstone: some target tables have UNIQUE(tenant_id, email)
    # (sup_agents, ops_team_members, sls_reps). A shared literal would collide when a
    # second subject in the same tenant is erased. Key on employee_id, else a stable
    # hash of the email, so re-runs stay idempotent but distinct subjects differ.
    tomb_email = _TOMBSTONE_EMAIL_FMT.format(
        employee_id or (_email_hash(email)[:16] if email else "subject"))

    subject_names, customer_ids, vendor_ids = await _collect_subject_identity(
        db, tables, tenant_id, employee_id, email)

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
            res = await db.execute(_skip_held(
                update(emp).where(emp.c.tenant_id == tenant_id).where(or_(*conds)).values(**values), emp
            ))
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
                paths = (await db.execute(_skip_held(
                    select(cand.c.resume_path).where(cand.c.tenant_id == tenant_id).where(or_(*conds)), cand
                ))).scalars().all()
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
            res = await db.execute(_skip_held(
                update(cand).where(cand.c.tenant_id == tenant_id).where(or_(*conds)).values(**values), cand
            ))
            affected["hr_candidates"] = int(res.rowcount or 0)

    # ── hr_employee_documents (collect file blob BEFORE tombstoning) ──────
    docs = tables.get("hr_employee_documents")
    if docs is not None and employee_id and "employee_id" in docs.c:
        if "file_path" in docs.c:
            paths = (await db.execute(_skip_held(
                select(docs.c.file_path).where(docs.c.tenant_id == tenant_id)
                .where(docs.c.employee_id == employee_id), docs
            ))).scalars().all()
            blob_paths.extend(p for p in paths if p)
        values = {}
        if "file_path" in docs.c:
            values["file_path"] = _TOMBSTONE
        if "title" in docs.c:
            values["title"] = _TOMBSTONE
        if values:
            res = await db.execute(_skip_held(
                update(docs).where(docs.c.tenant_id == tenant_id)
                .where(docs.c.employee_id == employee_id).values(**values), docs
            ))
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
                res = await db.execute(_skip_held(
                    update(apps).where(apps.c.tenant_id == tenant_id)
                    .where(apps.c.applicant_ref == ref).values(**values), apps
                ))
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
                res = await db.execute(_skip_held(
                    update(loans).where(loans.c.tenant_id == tenant_id)
                    .where(loans.c.application_id.in_(app_ids))
                    .values(borrower_name=_TOMBSTONE), loans
                ))
                affected["lnd_serviced_loans"] = int(res.rowcount or 0)

        # Collection cases carry a free-text contact log (phone/notes); clear it.
        cases = tables.get("lnd_collection_cases")
        if cases is not None and loan_ids and "serviced_loan_id" in cases.c \
                and "contact_log" in cases.c:
            res = await db.execute(_skip_held(
                update(cases).where(cases.c.tenant_id == tenant_id)
                .where(cases.c.serviced_loan_id.in_(loan_ids))
                .values(contact_log=[]), cases
            ))
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
                res = await db.execute(_skip_held(
                    update(enc).where(enc.c.tenant_id == tenant_id)
                    .where(enc.c.patient_ref == ref).values(**values), enc
                ))
                affected["hlth_encounters"] = int(res.rowcount or 0)

        consent = tables.get("hlth_consent_records")
        if consent is not None and "patient_ref" in consent.c:
            res = await db.execute(_skip_held(
                update(consent).where(consent.c.tenant_id == tenant_id)
                .where(consent.c.patient_ref == ref).values(patient_ref=_TOMBSTONE), consent
            ))
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
                res = await db.execute(_skip_held(
                    update(disc).where(disc.c.tenant_id == tenant_id)
                    .where(disc.c.encounter_id.in_(enc_ids)).values(**values), disc
                ))
                affected["hlth_phi_disclosures"] = int(res.rowcount or 0)

    # ── Sales, Finance, Support, Engineering, Operations: person rosters &
    #    external-person direct identifiers (email-matched) ─────────────────────
    # Sales contacts/leads, finance vendor/customer masters, and the support-agent /
    # engineer / ops-team-member rosters all hold a person's direct identifiers
    # keyed by their email. Same tombstone contract as the HR tables.
    if email:
        # (table, name-cols -> tombstone, cols -> null); each applied only if present.
        for tname, name_cols, null_cols in (
            ("sls_contacts", ("first_name", "last_name"), ("phone",)),
            ("sls_leads", ("contact_name",), ("phone",)),
            ("fin_vendors", (),
             ("phone", "tax_id", "bank_routing_number", "bank_account_number", "primary_contact")),
            ("fin_customers", (), ("phone", "tax_id", "primary_contact")),
            ("sls_reps", ("name",), ()),
            ("sup_agents", ("name",), ()),
            ("eng_engineers", ("name",), ("github_handle",)),
            ("ops_team_members", ("name",), ()),
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
            res = await db.execute(_skip_held(
                update(t).where(t.c.tenant_id == tenant_id).where(t.c.email == email).values(**values), t
            ))
            if res.rowcount:
                affected[tname] = int(res.rowcount)

        # ── Legal DSAR register: the request record's OWN requestor identity ──────
        # A DSAR row stores the requestor's name/email plus any uploaded evidence
        # file. Anonymise the subject's own request (matched on requestor_email) and
        # collect its evidence blob for deletion. Distinct email column, so handled
        # outside the loop above.
        dsar = tables.get("leg_data_subject_requests")
        if dsar is not None and "requestor_email" in dsar.c and "tenant_id" in dsar.c:
            if "evidence_path" in dsar.c:
                ev = (await db.execute(_skip_held(
                    select(dsar.c.evidence_path).where(dsar.c.tenant_id == tenant_id)
                    .where(dsar.c.requestor_email == email), dsar
                ))).scalars().all()
                blob_paths.extend(p for p in ev if p)
            values = {"requestor_email": tomb_email}
            if "requestor_name" in dsar.c:
                values["requestor_name"] = _TOMBSTONE
            if "evidence_path" in dsar.c:
                values["evidence_path"] = None
            res = await db.execute(_skip_held(
                update(dsar).where(dsar.c.tenant_id == tenant_id)
                .where(dsar.c.requestor_email == email).values(**values), dsar
            ))
            if res.rowcount:
                affected["leg_data_subject_requests"] = int(res.rowcount)

    # ── Support: CUSTOMER-authored ticket content (free-text; can carry PANs/SSNs)
    # Keyed via the subject's customer master id (fin_customers.id -> customer_id),
    # NOT email. description/body are NOT NULL, so tombstoned rather than nulled.
    if customer_ids:
        tkt = tables.get("sup_tickets")
        ticket_ids: list[str] = []
        if tkt is not None and "customer_id" in tkt.c and "description" in tkt.c:
            ticket_ids = list((await db.execute(
                select(tkt.c.id).where(tkt.c.tenant_id == tenant_id)
                .where(tkt.c.customer_id.in_(customer_ids))
            )).scalars().all())
            if ticket_ids:
                res = await db.execute(_skip_held(
                    update(tkt).where(tkt.c.tenant_id == tenant_id)
                    .where(tkt.c.customer_id.in_(customer_ids))
                    .values(description=_TOMBSTONE), tkt
                ))
                affected["sup_tickets"] = int(res.rowcount or 0)
        cmt = tables.get("sup_ticket_comments")
        if cmt is not None and ticket_ids and {"ticket_id", "body"} <= set(cmt.c.keys()):
            stmt = (update(cmt).where(cmt.c.tenant_id == tenant_id)
                    .where(cmt.c.ticket_id.in_(ticket_ids)))
            # Only the CUSTOMER's own words are the subject's PII; agent/system
            # comments belong to other people and stay.
            if "author_type" in cmt.c:
                stmt = stmt.where(cmt.c.author_type == "CUSTOMER")
            res = await db.execute(_skip_held(stmt.values(body=_TOMBSTONE), cmt))
            if res.rowcount:
                affected["sup_ticket_comments"] = int(res.rowcount)

    # ── Procurement + Legal: free-text PERSON/party fields ─────────────────
    # vendor_name is reachable via the subject's vendor master id (reliable FK).
    if vendor_ids:
        po = tables.get("ops_purchase_orders")
        if po is not None and {"vendor_id", "vendor_name"} <= set(po.c.keys()):
            res = await db.execute(_skip_held(
                update(po).where(po.c.tenant_id == tenant_id)
                .where(po.c.vendor_id.in_(vendor_ids)).values(vendor_name=_TOMBSTONE), po
            ))
            if res.rowcount:
                affected["ops_purchase_orders"] = int(res.rowcount)

    # requested_by holds an employee id OR a name; receiver_name / counterparty hold
    # a name only. No id/email key exists on these columns, so they are matched
    # against the subject's collected identity (id + name(s)), tenant-scoped.
    # ponytail: exact tenant-scoped name match is the floor — it can over-erase a
    # namesake or miss a spelling variant. A real party-master FK on these columns
    # is the correct upgrade; add it when procurement/legal grow one.
    pr_match = list(subject_names) + ([employee_id] if employee_id else [])
    if pr_match:
        pr = tables.get("ops_purchase_requests")
        if pr is not None and "requested_by" in pr.c:
            res = await db.execute(_skip_held(
                update(pr).where(pr.c.tenant_id == tenant_id)
                .where(pr.c.requested_by.in_(pr_match)).values(requested_by=_TOMBSTONE), pr
            ))
            if res.rowcount:
                affected["ops_purchase_requests"] = int(res.rowcount)
    if subject_names:
        names = list(subject_names)
        gr = tables.get("ops_goods_receipts")
        if gr is not None and "receiver_name" in gr.c:
            res = await db.execute(_skip_held(
                update(gr).where(gr.c.tenant_id == tenant_id)
                .where(gr.c.receiver_name.in_(names)).values(receiver_name=_TOMBSTONE), gr
            ))
            if res.rowcount:
                affected["ops_goods_receipts"] = int(res.rowcount)
        lc = tables.get("leg_contracts")
        if lc is not None and "counterparty" in lc.c:
            res = await db.execute(_skip_held(
                update(lc).where(lc.c.tenant_id == tenant_id)
                .where(lc.c.counterparty.in_(names)).values(counterparty=_TOMBSTONE), lc
            ))
            if res.rowcount:
                affected["leg_contracts"] = int(res.rowcount)

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

    # ── Graph store (M13): a Knowledge node's name is content[:48] and can carry
    # the subject's PII, and it survived erasure because only DB rows, blobs and
    # vectors were purged. Delete this tenant's nodes matching the subject.
    graph_nodes_deleted = 0
    try:
        from app.core.polystore import get_graph_store
        terms = [t for t in ([email] + list(subject_names or [])) if t]
        graph_nodes_deleted = await get_graph_store().delete_subject(tenant_id, terms)
    except Exception as exc:
        logger.warning("[PrivacyErasure] graph-node purge skipped: %s", exc)

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
        "graph_nodes_deleted": graph_nodes_deleted,
        "note": (
            "Direct identifiers tombstoned across the HR, sales, finance, support, "
            "engineering, operations, legal, healthcare and lending tables; customer "
            "support ticket content, procurement person fields and legal contract "
            "counterparty anonymised; stored files deleted from the blob layer; "
            "subject embeddings purged from the vector store; rows under legal hold "
            "preserved; erasure journaled to the DB and a DR-safe external sink for "
            "backup-restore replay. Hash-chained ledger references are retained by design."
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
    # tenant -> {email_hash: email}, built on first need. Without this, every
    # email-keyed entry re-scanned every people table: O(entries x all-emails).
    # A hash already erased earlier in this pass still resolves from the index;
    # re-erasing it is an idempotent no-op, so the reuse is safe.
    indexes: dict[str, dict[str, str]] = {}
    for entry in entries:
        try:
            if entry.operation == "PURGE_TENANT":
                await purge_tenant(db, entry.tenant_id)
            elif entry.subject_employee_id:
                await erase_subject(db, entry.tenant_id,
                                    employee_id=entry.subject_employee_id, _journal=False)
            elif entry.subject_email_hash:
                if entry.tenant_id not in indexes:
                    indexes[entry.tenant_id] = await _email_hash_index(db, entry.tenant_id)
                email = indexes[entry.tenant_id].get(entry.subject_email_hash)
                if email:
                    await erase_subject(db, entry.tenant_id, email=email, _journal=False)
            entry.replayed_at = datetime.now(timezone.utc)
            replayed += 1
        except Exception as exc:  # one bad entry must not abort the replay
            logger.warning("[PrivacyErasure] replay failed for %s: %s", entry.id, exc)
    await db.commit()
    logger.info("[PrivacyErasure] replayed %d/%d deletion-journal entries", replayed, len(entries))
    return {"entries": len(entries), "replayed": replayed}


async def replay_deletions_from_external(
    db: AsyncSession, tenant_id: Optional[str] = None
) -> dict:
    """Replay erasures from the DR-safe EXTERNAL sink after a restore wiped the DB
    journal table.

    The DB-backed journal lives in the same database a restore wipes, so
    ``replay_deletions`` alone cannot see erasures that predate the backup. The
    external file sink survives the restore; this re-applies each of its entries
    that is NOT already present as a live DB journal row. Erasure is idempotent, so
    replaying an entry that the restore happened to keep is harmless.
    """
    from app.models.settings import DeletionJournal
    import app.core.database  # noqa: F401

    external = deletion_sink.read_all()

    # Keys the DB journal still knows (survived the restore or were re-created since).
    q = select(
        DeletionJournal.tenant_id, DeletionJournal.operation,
        DeletionJournal.subject_employee_id, DeletionJournal.subject_email_hash,
    )
    if tenant_id:
        q = q.where(DeletionJournal.tenant_id == tenant_id)
    known = {tuple(r) for r in (await db.execute(q)).all()}

    seen = replayed = 0
    indexes: dict[str, dict[str, str]] = {}  # tenant -> {email_hash: email}, see replay_deletions
    for e in external:
        etid = e.get("tenant_id")
        if tenant_id and etid != tenant_id:
            continue
        seen += 1
        key = (etid, e.get("operation"), e.get("employee_id"), e.get("email_hash"))
        if key in known:
            continue  # already reflected in the DB after restore — nothing to do
        try:
            op = e.get("operation")
            if op == "PURGE_TENANT":
                await purge_tenant(db, etid)
            elif e.get("employee_id"):
                await erase_subject(db, etid, employee_id=e["employee_id"], _journal=False)
            elif e.get("email_hash"):
                if etid not in indexes:
                    indexes[etid] = await _email_hash_index(db, etid)
                email = indexes[etid].get(e["email_hash"])
                if email:
                    await erase_subject(db, etid, email=email, _journal=False)
            replayed += 1
        except Exception as exc:  # one bad entry must not abort the replay
            logger.warning("[PrivacyErasure] external-sink replay failed for %s: %s", key, exc)
    logger.info(
        "[PrivacyErasure] external-sink replay: %d/%d entries re-applied", replayed, seen)
    return {"external_entries": seen, "replayed": replayed}


async def _email_hash_index(db: AsyncSession, tenant_id: str) -> dict[str, str]:
    """Build ``{sha256(email): email}`` for one tenant in a single pass.

    Replay resolves many journal entries against the same tenant, so the scan is
    done ONCE and shared instead of once per entry. Memory is bounded by one
    tenant's people rows, and only the email column is loaded - the same data a
    single lookup already pulled.
    """
    from app.models.domain import Base
    import app.core.database  # noqa: F401

    tables = Base.metadata.tables
    index: dict[str, str] = {}
    for tname in ("hr_employees", "hr_candidates",
                  "sls_contacts", "sls_leads", "sls_reps", "fin_vendors", "fin_customers",
                  "sup_agents", "eng_engineers", "ops_team_members"):
        t = tables.get(tname)
        if t is None or "email" not in t.c or "tenant_id" not in t.c:
            continue
        emails = (await db.execute(
            select(t.c.email).where(t.c.tenant_id == tenant_id)
        )).scalars().all()
        for e in emails:
            if e:
                # setdefault keeps the first table in the list winning, which is
                # the row the old per-lookup scan would have returned.
                index.setdefault(_email_hash(e), e)
    return index


async def _find_email_by_hash(db: AsyncSession, tenant_id: str, email_hash: str) -> Optional[str]:
    """Locate a live email whose SHA-256 matches, without storing raw email.

    Single-shot wrapper; the replay loops build the index once and reuse it.
    """
    return (await _email_hash_index(db, tenant_id)).get(email_hash)


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
        "leg_contracts": ("document_path", "counterparty"),
        "leg_court_filings": ("document_path",),
        "sup_tickets": ("customer_id", "description"),
        "sup_ticket_comments": ("ticket_id", "body", "author_type"),
        "ops_purchase_requests": ("requested_by",),
        "ops_goods_receipts": ("receiver_name",),
        "ops_purchase_orders": ("vendor_id", "vendor_name"),
        "sls_reps": ("email", "name"),
        "sup_agents": ("email", "name"),
        "eng_engineers": ("email", "name", "github_handle"),
        "ops_team_members": ("email", "name"),
        "leg_data_subject_requests": ("requestor_email", "requestor_name", "evidence_path"),
        "fin_invoices": ("attachment_paths",),
        "fin_expense_items": ("receipt_path",),
        "fin_control_tests": ("evidence_path",),
        "fin_reports": ("export_path",),
    }
    for _name, _cols in _expected.items():
        assert _name in _t, f"erasure target table missing: {_name}"
        for _c in _cols:
            assert _c in _t[_name].c, f"{_name}.{_c} renamed; erasure now skips it"
    print("privacy_erasure schema self-check OK")

    # Legal-hold guard: the filter must be added only when the column exists, and
    # must exclude held rows (fail-closed) while a plain table is left untouched.
    from sqlalchemy import (
        Table as _Tbl, Column as _Col, MetaData as _MD, String as _Str,
        Boolean as _Bool, delete as _del,
    )
    _md = _MD()
    _held = _Tbl("_t_held", _md, _Col("tenant_id", _Str), _Col("on_legal_hold", _Bool))
    _plain = _Tbl("_t_plain", _md, _Col("tenant_id", _Str))
    _s = _del(_held).where(_held.c.tenant_id == "x")
    assert "on_legal_hold" in str(_skip_held(_s, _held)), "hold guard must exclude held rows"
    _p = _del(_plain).where(_plain.c.tenant_id == "x")
    assert _skip_held(_p, _plain) is _p, "hold guard must be a no-op without the column"
    print("privacy_erasure legal-hold guard self-check OK")
