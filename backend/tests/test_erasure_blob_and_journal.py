"""Erasure completeness: blob deletion + deletion-journal replay.

Proves the two honest boundaries that erasure previously did NOT cross are now
crossed:
  * the stored FILE (resume/document blob) is actually deleted, not just its DB
    pointer nulled;
  * a restored backup cannot silently resurrect a subject, because the deletion
    journal replays every erasure (by id, and by email-hash without storing raw
    email).
"""
from datetime import date

import pytest
from sqlalchemy import select

from app.core.polystore import blob_store
from app.services.privacy_erasure import erase_subject, replay_deletions
from app.hr.models.recruiting import Candidate
from app.hr.models.core import HREmployee
from app.models.settings import DeletionJournal

TENANT = "tenant_acme"


# ── blob_store unit tests ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_blob_local_file(tmp_path):
    f = tmp_path / "resume.pdf"
    f.write_text("secret resume PII")
    res = await blob_store.delete_blob(str(f))
    assert res["deleted"] is True and res["backend"] == "local"
    assert not f.exists()


@pytest.mark.asyncio
async def test_delete_blob_missing_and_tombstone(tmp_path):
    assert (await blob_store.delete_blob(str(tmp_path / "nope.pdf")))["deleted"] is False
    assert (await blob_store.delete_blob("[ERASED]"))["deleted"] is False
    assert (await blob_store.delete_blob(None))["deleted"] is False


@pytest.mark.asyncio
async def test_delete_blobs_dedupes_and_aggregates(tmp_path):
    a = tmp_path / "a.pdf"; a.write_text("x")
    b = tmp_path / "b.pdf"; b.write_text("y")
    result = await blob_store.delete_blobs([str(a), str(b), str(a), "[ERASED]", None])
    assert result["attempted"] == 2      # deduped; tombstone/None skipped
    assert result["deleted"] == 2


@pytest.mark.asyncio
async def test_unsupported_scheme_is_honest_not_fatal():
    res = await blob_store.delete_blob("ftp://host/file")
    assert res["deleted"] is False
    assert "unsupported" in res.get("error", "")


# ── erase_subject deletes the real stored file ────────────────────────────────

@pytest.mark.asyncio
async def test_erase_subject_deletes_resume_blob(db, tmp_path):
    resume = tmp_path / "ada_resume.pdf"
    resume.write_text("Ada Lovelace resume with PII")
    cand = Candidate(
        tenant_id=TENANT, requisition_id="req_x",
        first_name="Ada", last_name="Lovelace",
        email="ada.c@example.com", resume_path=str(resume),
    )
    db.add(cand)
    await db.commit()

    receipt = await erase_subject(db, TENANT, email="ada.c@example.com")
    assert receipt["blobs_deleted"] == 1
    assert not resume.exists(), "the resume file must be deleted, not just the pointer"


# ── deletion journal + replay ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_journal_written_and_replay_by_id(db):
    emp = HREmployee(
        tenant_id=TENANT, first_name="Grace", last_name="Hopper",
        email="grace@example.com", hire_date=date(2020, 1, 1), job_title="Engineer",
    )
    db.add(emp)
    await db.commit()
    emp_id = emp.id

    await erase_subject(db, TENANT, employee_id=emp_id)

    entries = (await db.execute(
        select(DeletionJournal).where(DeletionJournal.tenant_id == TENANT)
    )).scalars().all()
    assert any(e.operation == "ERASE_SUBJECT" and e.subject_employee_id == emp_id
               for e in entries)

    # Simulate a backup restore: the subject's PII reappears on the row.
    db.expire_all()
    row = (await db.execute(select(HREmployee).where(HREmployee.id == emp_id))).scalar_one()
    row.first_name, row.last_name, row.email = "Grace", "Hopper", "grace@example.com"
    await db.commit()

    result = await replay_deletions(db, tenant_id=TENANT)
    assert result["replayed"] >= 1

    db.expire_all()
    row2 = (await db.execute(select(HREmployee).where(HREmployee.id == emp_id))).scalar_one()
    assert row2.first_name == "[ERASED]", "replay must re-erase the restored PII"


@pytest.mark.asyncio
async def test_replay_by_email_hash_without_storing_raw_email(db):
    emp = HREmployee(
        tenant_id=TENANT, first_name="Katherine", last_name="Johnson",
        email="kat@example.com", hire_date=date(2020, 1, 1), job_title="Engineer",
    )
    db.add(emp)
    await db.commit()
    emp_id = emp.id

    await erase_subject(db, TENANT, email="kat@example.com")

    entry = (await db.execute(
        select(DeletionJournal).where(DeletionJournal.subject_employee_id.is_(None))
    )).scalars().first()
    assert entry is not None and entry.subject_email_hash
    assert "kat@example.com" not in (entry.subject_email_hash or ""), "raw email must never be journaled"

    # Restore the PII, then replay: the entry has only a hash, yet replay re-erases.
    db.expire_all()
    row = (await db.execute(select(HREmployee).where(HREmployee.id == emp_id))).scalar_one()
    row.first_name, row.email = "Katherine", "kat@example.com"
    await db.commit()

    await replay_deletions(db, tenant_id=TENANT)

    db.expire_all()
    row2 = (await db.execute(select(HREmployee).where(HREmployee.id == emp_id))).scalar_one()
    assert row2.first_name == "[ERASED]"
