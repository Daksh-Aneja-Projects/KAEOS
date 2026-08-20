"""S5.3.7 + S5.3.8 - unbounded repeated scans, bounded.

3.7 ``/reports/compliance`` ran one ``cast(compliance_tags AS TEXT) LIKE '%FW%'``
    per framework: five unindexable full scans of the tenant's rules per report.
    Now one scan, counted in Python, with tag matching ANCHORED at the start of a
    tag instead of matching anywhere in the JSON array text.

3.8 ``_find_email_by_hash`` streamed every email from ten tables per lookup, and
    the two replay paths called it once PER JOURNAL ENTRY. The scan is now built
    once per tenant per replay pass and shared.
"""
import uuid

from app.api.routes.enterprise import generate_compliance_report
from app.models.domain import Rule
from app.models.settings import DeletionJournal
from app.services import privacy_erasure
from app.services.privacy_erasure import (
    _email_hash,
    _email_hash_index,
    _find_email_by_hash,
    replay_deletions,
)

A = "tenant_scan_a"
B = "tenant_scan_b"


def _rule(tenant, tags):
    return Rule(id=str(uuid.uuid4()), tenant_id=tenant, statement="s",
                trigger_json={}, action_json={}, compliance_tags=tags)


async def _coverage(db, tenant=A):
    report = await generate_compliance_report(tenant_id=tenant, db=db)
    return {f["framework"]: f for f in report["framework_coverage"]}


# ---------------------------------------------------------------- 3.7 counting


async def test_compliance_coverage_counts_per_tenant(db):
    db.add_all([
        _rule(A, ["SOX"]),
        _rule(A, ["GDPR", "SOX"]),   # counts once for SOX AND once for GDPR
        _rule(A, []),                # no tags: counts for nothing
        _rule(B, ["SOX"]),           # another tenant: must not leak into A
    ])
    await db.commit()

    cov = await _coverage(db)
    assert cov["SOX"]["rule_count"] == 2
    assert cov["SOX"]["coverage"] == "COVERED"
    assert cov["GDPR"]["rule_count"] == 1
    assert cov["GDPR"]["coverage"] == "COVERED"
    for fw in ("HIPAA", "PCI", "CCPA"):
        assert cov[fw]["rule_count"] == 0
        assert cov[fw]["coverage"] == "GAP"

    # Tenant B sees only its own rule.
    assert (await _coverage(db, B))["SOX"]["rule_count"] == 1
    assert (await _coverage(db, B))["GDPR"]["rule_count"] == 0


async def test_framework_family_tags_count_but_midstring_matches_do_not(db):
    """DOCUMENTED semantic change from the old ``LIKE '%FW%'``.

    Matching is anchored at the start of an individual tag. Free-text framework
    labels the regulatory engine writes ("PCI-DSS v4.0", "SOX_2026") still count
    for their family; a tag that merely CONTAINS a framework name ("EU_GDPR")
    no longer does - the old substring match over the whole JSON array text
    counted it, which over-reported coverage.
    """
    db.add_all([
        _rule(A, ["PCI-DSS v4.0"]),   # prefix: counts for PCI
        _rule(A, ["SOX_2026"]),       # prefix: counts for SOX
        _rule(A, ["EU_GDPR"]),        # mid-string only: does NOT count for GDPR
        _rule(A, ["GDPR", "GDPR_UK"]),  # two tags, one family: the RULE counts once
    ])
    await db.commit()

    cov = await _coverage(db)
    assert cov["PCI"]["rule_count"] == 1
    assert cov["SOX"]["rule_count"] == 1
    assert cov["GDPR"]["rule_count"] == 1, "EU_GDPR must not count; GDPR+GDPR_UK counts once"
    assert cov["GDPR"]["coverage"] == "COVERED"
    assert cov["HIPAA"]["coverage"] == "GAP"


async def test_compliance_report_survives_a_string_tags_value(db):
    """A JSON column handed back as raw text must not explode the report."""
    r = _rule(A, ["SOX"])
    db.add(r)
    await db.commit()
    r.compliance_tags = "SOX"  # defensive path, no commit needed for the read below
    cov = await _coverage(db)
    assert cov["SOX"]["rule_count"] == 1


# ---------------------------------------------------------- 3.8 email-hash index


class _CountingSession:
    """Delegating proxy that counts ``execute`` calls."""

    def __init__(self, inner):
        self._inner = inner
        self.executes = 0

    async def execute(self, *args, **kwargs):
        self.executes += 1
        return await self._inner.execute(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._inner, name)


async def _seed_people(db):
    from app.hr.models.core import HREmployee
    from app.sales.models.accounts import Account, Contact
    from datetime import date

    def emp(tenant, email):
        return HREmployee(tenant_id=tenant, first_name="Sam", last_name="Doe",
                          email=email, hire_date=date(2024, 1, 1), job_title="Analyst")

    acct = Account(tenant_id=A, name="Scan Co")
    db.add(acct)
    await db.commit()
    await db.refresh(acct)

    db.add_all([
        emp(A, "alpha@example.com"),
        emp(A, "beta@example.com"),
        emp(B, "gamma@example.com"),          # other tenant, must stay invisible to A
        Contact(tenant_id=A, account_id=acct.id, first_name="Cee", last_name="Dee",
                email="delta@example.com"),
    ])
    await db.commit()


async def test_find_email_by_hash_is_tenant_scoped(db):
    await _seed_people(db)

    assert await _find_email_by_hash(db, A, _email_hash("alpha@example.com")) == "alpha@example.com"
    assert await _find_email_by_hash(db, A, _email_hash("delta@example.com")) == "delta@example.com"
    # Tenant B's person is not resolvable from tenant A, and vice versa.
    assert await _find_email_by_hash(db, A, _email_hash("gamma@example.com")) is None
    assert await _find_email_by_hash(db, B, _email_hash("alpha@example.com")) is None
    assert await _find_email_by_hash(db, A, _email_hash("nobody@example.com")) is None


async def test_index_resolves_many_hashes_without_more_round_trips(db):
    """The whole point of 3.8: lookups must not scale the DB round-trips."""
    await _seed_people(db)
    counting = _CountingSession(db)

    index = await _email_hash_index(counting, A)
    after_build = counting.executes
    assert after_build > 0

    resolved = [index.get(_email_hash(e)) for e in
                ("alpha@example.com", "beta@example.com", "delta@example.com")]
    assert resolved == ["alpha@example.com", "beta@example.com", "delta@example.com"]
    assert index.get(_email_hash("gamma@example.com")) is None  # tenant-scoped
    assert counting.executes == after_build, "resolving a hash must cost zero queries"


async def test_replay_scans_once_per_tenant_not_once_per_entry(db, monkeypatch):
    """Old code: one full ten-table scan PER journal entry. New: one per tenant."""
    await _seed_people(db)

    calls = []
    real_index = privacy_erasure._email_hash_index

    async def counting_index(session, tenant_id):
        calls.append(tenant_id)
        return await real_index(session, tenant_id)

    monkeypatch.setattr(privacy_erasure, "_email_hash_index", counting_index)

    db.add_all([
        DeletionJournal(tenant_id=A, operation="ERASE_SUBJECT",
                        subject_email_hash=_email_hash(e))
        for e in ("alpha@example.com", "beta@example.com", "delta@example.com")
    ])
    await db.commit()

    result = await replay_deletions(db, tenant_id=A)

    assert result["entries"] == 3 and result["replayed"] == 3
    assert calls == [A], f"one scan per tenant, got {len(calls)}: {calls}"

    # The replay really erased: the emails no longer resolve to their old value.
    db.expire_all()
    assert await _find_email_by_hash(db, A, _email_hash("alpha@example.com")) is None
