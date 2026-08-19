"""
QUERY-BUDGET harness — pins per-endpoint DB statement counts so an N+1 or an
unbounded full-row scan regression fails CI.

A ``before_cursor_execute`` listener on the test engine (the one backing the
``get_db`` override, see conftest) counts every SQL statement issued while a hot
read endpoint runs through the ASGI client. We assert:

  1. the statement count stays at-or-below a documented budget (a ratchet set a
     little above the current observed count — catches N+1 fan-out), and
  2. no SELECT does a full-ORM-row load of the fast-growing ``rules`` table
     without a LIMIT (catches the "reverted the freshness projection back to
     ``select(Rule)``" unbounded-scan regression). Full Rule rows carry the wide
     ``rules.statement`` text column; the freshness/tier queries are column-only
     projections or GROUP BY aggregates that never select it.

MEASURED on the clean tree (SQLite in-memory, seeded rows below), 2026-08-17:
    GET /api/v1/dashboard/health        18 statements
    GET /api/v1/org/pulse               58 statements
    GET /api/v1/workforce/departments    1 statement
Budgets are set at observed + slack so this is a ratchet, not a flake.

EXTENDED 2026-08-19 for the hot-path sprint's count-collapse + N+1 fixes. Each
is seeded with 8 rows so a per-row regression fans out visibly. Measured on the
fixed tree, with what the pre-fix shape cost for the same seed:
    GET  /api/v1/system/stats                            1  (was 15)
    GET  /api/v1/support/kb/articles                     2  (was 9)
    GET  /api/v1/operations/vendors                      2  (was 9)
    POST /api/v1/hr/payroll-runs/{id}/generate-payslips  6  (was 13)
NOT covered: ActivityFeedService.get_unread_count (and its
/agent-factory/agents/activity-feed route) runs on its own AsyncSessionLocal,
i.e. conftest's SIDECAR app engine, which this counter does not listen to;
DeploymentStudio's agent-count collapse is not reachable from an endpoint
without standing up a whole deployment. Both are covered behaviourally in
tests/test_count_query_collapse.py instead.

Unit-level: reuses conftest's async_client/db fixtures; no LLM.
"""
import re

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import ConfidenceTier, Rule, Skill
from app.workforce.models.core import Department

from tests.conftest import test_engine

TENANT = "tenant_acme"  # dev-mode default tenant (app/core/tenant.py)

# A full Rule ORM row selects this wide text column; the health endpoint's
# freshness/tier scans are projections/aggregates that must never load it
# unbounded. Any SELECT that pulls it must be LIMIT-bounded (the decay-alerts
# query is `select(Rule)...limit(10)` — allowed).
_WIDE_RULE_COL = "rules.statement"


class _StatementCounter:
    """Capture every SQL statement issued on the test engine during a block."""

    def __init__(self):
        self.statements: list[str] = []

    def _on_execute(self, conn, cursor, statement, parameters, context, executemany):
        self.statements.append(statement)

    def __enter__(self):
        event.listen(test_engine.sync_engine, "before_cursor_execute", self._on_execute)
        return self

    def __exit__(self, *exc):
        event.remove(test_engine.sync_engine, "before_cursor_execute", self._on_execute)

    @property
    def selects(self) -> list[str]:
        return [s for s in self.statements if s.lstrip().upper().startswith("SELECT")]

    def unbounded_rule_row_loads(self) -> list[str]:
        """SELECTs that load full Rule rows (select the wide text column) with no LIMIT."""
        bad = []
        for s in self.selects:
            low = s.lower()
            if _WIDE_RULE_COL in low and not re.search(r"\blimit\b", low):
                bad.append(s)
        return bad


async def _seed_rules(db: AsyncSession, n: int = 6):
    """Rows in the fast-growing tables so a per-row (N+1) regression actually fires."""
    for i in range(n):
        db.add(Rule(
            id=f"rule-{i}", tenant_id=TENANT, statement=f"rule {i}",
            trigger_json={}, action_json={}, is_archived=False, is_executable=True,
            confidence_scalar=0.6, confidence_tier=ConfidenceTier.INFERRED,
            domain="finance", half_life_days=30,
        ))
    db.add(Skill(id="sk-1", skill_id="s1", tenant_id=TENANT, department="finance",
                 domain="finance", status="ACTIVE", confidence=0.9))
    await db.commit()


@pytest.mark.asyncio
async def test_dashboard_health_query_budget(async_client: AsyncClient, db: AsyncSession):
    await _seed_rules(db)
    with _StatementCounter() as counter:
        r = await async_client.get("/api/v1/dashboard/health")
    assert r.status_code == 200, r.text

    # Budget: observed 18 on the clean tree — fixed-cardinality metric counts
    # (rule/skill/execution totals, execution status breakdown, tier + domain
    # GROUP BYs), none of which scale with row count. An N+1 over rules/skills/
    # executions would fan out per row and blow well past this ratchet.
    assert len(counter.statements) <= 22, (
        f"/dashboard/health issued {len(counter.statements)} statements "
        f"(budget 22). N+1 regression?\n" + "\n".join(counter.statements)
    )
    # The freshness + tier reads must stay column-only / GROUP BY, never a full
    # unbounded `select(Rule)` load of the wide table.
    bad = counter.unbounded_rule_row_loads()
    assert not bad, "Unbounded full-Rule-row scan (missing LIMIT/projection):\n" + "\n".join(bad)


@pytest.mark.asyncio
async def test_org_pulse_query_budget(async_client: AsyncClient, db: AsyncSession):
    await _seed_rules(db)
    with _StatementCounter() as counter:
        r = await async_client.get("/api/v1/org/pulse")
    assert r.status_code == 200, r.text

    # Budget: observed 58 (ten domain analytics + the workflow SLA sweep, all
    # fixed-shape aggregate queries). This ratchet fails if a domain analytics
    # fn or the sweep starts issuing a query per row.
    assert len(counter.statements) <= 72, (
        f"/org/pulse issued {len(counter.statements)} statements (budget 72). "
        f"Per-row fan-out in a domain analytics fn or the SLA sweep?\n"
        + "\n".join(counter.statements)
    )


@pytest.mark.asyncio
async def test_workforce_departments_query_budget(async_client: AsyncClient, db: AsyncSession):
    for i in range(8):
        db.add(Department(id=f"dept-{i}", tenant_id=TENANT, name=f"D{i}",
                          slug=f"d{i}", status="ACTIVE"))
    await db.commit()

    with _StatementCounter() as counter:
        r = await async_client.get("/api/v1/workforce/departments")
    assert r.status_code == 200, r.text

    # Budget: the list is a single SELECT regardless of department count. A
    # per-department query (e.g. loading agents/capabilities per row) breaks this.
    assert len(counter.statements) <= 3, (
        f"/workforce/departments issued {len(counter.statements)} statements "
        f"(budget 3) for 8 departments — N+1 per department?\n"
        + "\n".join(counter.statements)
    )


@pytest.mark.asyncio
async def test_system_stats_query_budget(async_client: AsyncClient, db: AsyncSession):
    await _seed_rules(db)
    with _StatementCounter() as counter:
        r = await async_client.get("/api/v1/system/stats")
    assert r.status_code == 200, r.text

    # Budget: observed 1 — all 13 entity COUNTs plus the 2 AVGs are scalar
    # subqueries in a single SELECT. The pre-collapse shape was a COUNT per
    # table in a Python loop (15 round trips), so this ratchet fails the moment
    # anyone re-introduces per-table queries.
    assert len(counter.statements) <= 3, (
        f"/system/stats issued {len(counter.statements)} statements (budget 3). "
        f"The 13 counts + 2 averages must stay one SELECT of scalar subqueries, "
        f"not a query per table.\n" + "\n".join(counter.statements)
    )


@pytest.mark.asyncio
async def test_kb_articles_query_budget(async_client: AsyncClient, db: AsyncSession):
    from app.support.models.knowledge import KBArticle, KBCategory

    for i in range(3):
        db.add(KBCategory(id=f"kbcat-{i}", tenant_id=TENANT, name=f"Cat {i}", slug=f"cat-{i}"))
    for i in range(8):
        db.add(KBArticle(id=f"kbart-{i}", tenant_id=TENANT, title=f"A{i}",
                         content_md="body", category_id=f"kbcat-{i % 3}", is_published=True))
    await db.commit()

    with _StatementCounter() as counter:
        r = await async_client.get("/api/v1/support/kb/articles")
    assert r.status_code == 200, r.text
    assert len(r.json()) == 8

    # Budget: observed 2 — the article page, then ONE batched category lookup
    # (WHERE id IN (...)). The pre-fix shape queried KBCategory once per article
    # with a category, i.e. 9 here and up to 501 at the endpoint's limit=500.
    assert len(counter.statements) <= 4, (
        f"/support/kb/articles issued {len(counter.statements)} statements "
        f"(budget 4) for 8 articles — category lookup back to one query per "
        f"article?\n" + "\n".join(counter.statements)
    )


@pytest.mark.asyncio
async def test_vendors_query_budget(async_client: AsyncClient, db: AsyncSession):
    from app.operations.models.vendors import VendorContract, VendorPerformance

    for i in range(8):
        db.add(VendorContract(id=f"vc-{i}", tenant_id=TENANT, vendor_name=f"V{i}",
                              service_provided="Hosting", contract_value=1000.0))
    await db.flush()
    for i in range(8):
        for j in range(2):
            db.add(VendorPerformance(id=f"vp-{i}-{j}", tenant_id=TENANT,
                                     vendor_contract_id=f"vc-{i}",
                                     overall_performance_score=90.0 + j))
    await db.commit()

    with _StatementCounter() as counter:
        r = await async_client.get("/api/v1/operations/vendors")
    assert r.status_code == 200, r.text
    assert len(r.json()) == 8

    # Budget: observed 2 — the contract page, then ONE batched performance read
    # ordered newest-first and collapsed per contract. The pre-fix shape ran a
    # LIMIT-1 performance query per contract: 9 here, up to 201 at limit=200.
    assert len(counter.statements) <= 4, (
        f"/operations/vendors issued {len(counter.statements)} statements "
        f"(budget 4) for 8 contracts — performance lookup back to one query per "
        f"contract?\n" + "\n".join(counter.statements)
    )


@pytest.mark.asyncio
async def test_generate_payslips_query_budget(async_client: AsyncClient, db: AsyncSession):
    from datetime import date

    from app.hr.models.compensation import Compensation
    from app.hr.models.core import EmploymentStatus, HREmployee
    from app.hr.models.payroll import PayrollRun

    for i in range(8):
        db.add(HREmployee(id=f"hre-{i}", tenant_id=TENANT, first_name="T", last_name=f"E{i}",
                          email=f"t.e{i}@kaeos.io", status=EmploymentStatus.ACTIVE,
                          hire_date=date(2024, 1, 1), job_title="Engineer"))
    await db.flush()
    for i in range(8):
        db.add(Compensation(id=f"hrc-{i}", tenant_id=TENANT, employee_id=f"hre-{i}",
                            base_amount=100000.0, effective_date=date(2024, 1, 1),
                            is_current=True))
    db.add(PayrollRun(id="hrpr-1", tenant_id=TENANT, period_start=date(2026, 1, 1),
                      period_end=date(2026, 1, 15), pay_date=date(2026, 1, 20)))
    await db.commit()

    with _StatementCounter() as counter:
        r = await async_client.post("/api/v1/hr/payroll-runs/hrpr-1/generate-payslips")
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 8

    # Budget: observed 6, and that shape is fixed no matter how many employees
    # the run covers — run lookup, already-paid employee ids, the employee list,
    # ONE batched current-compensation read, the run-total UPDATE, and a single
    # executemany INSERT of all payslips. The pre-fix shape added a
    # current-compensation SELECT per employee: 13 here, 1000+ on a real run.
    assert len(counter.statements) <= 8, (
        f"generate-payslips issued {len(counter.statements)} statements "
        f"(budget 8) for 8 employees — compensation lookup back to one query "
        f"per employee?\n" + "\n".join(counter.statements)
    )
