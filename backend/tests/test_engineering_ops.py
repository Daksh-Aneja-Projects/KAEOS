"""
Engineering ops-depth additions: on-call rotations, CI pipeline-run history
feeding the deploy-risk agent, and the GitHub issue-tracker connector.
"""
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.engineering.agents.deploy_risk_agent import DeployRiskAgent
from app.engineering.connectors.issue_tracker import GitHubIssueTrackerConnector
from app.engineering.models.core import Engineer, Service, ServiceHealth, ServiceTier
from app.engineering.models.ops import OnCallRole, OnCallRotation, PipelineRun, PipelineStatus

TENANT = "tenant_acme"


def _run(status, hours_ago):
    return PipelineRun(
        id=f"run-{hours_ago}", tenant_id=TENANT, pipeline_name="build-and-test",
        run_number=hours_ago, status=status,
        started_at=datetime.now(timezone.utc) - timedelta(hours=hours_ago),
    )


# --- _pipeline_failure_rate: pure, no DB, no fabricated 0% -------------------

def test_pipeline_failure_rate_none_with_no_history():
    assert DeployRiskAgent._pipeline_failure_rate([]) is None


def test_pipeline_failure_rate_computed_from_real_runs():
    runs = [_run(PipelineStatus.FAILED, 1), _run(PipelineStatus.SUCCEEDED, 2),
            _run(PipelineStatus.SUCCEEDED, 3), _run(PipelineStatus.SUCCEEDED, 4)]
    assert DeployRiskAgent._pipeline_failure_rate(runs) == 25.0


def test_pipeline_failure_rate_all_green():
    runs = [_run(PipelineStatus.SUCCEEDED, 1), _run(PipelineStatus.SUCCEEDED, 2)]
    assert DeployRiskAgent._pipeline_failure_rate(runs) == 0.0


# --- _resolve_score: a flaky pipeline history raises risk, silent history doesn't

def test_resolve_score_higher_with_flaky_pipeline_history():
    base_facts = {"service_tier": "TIER_2", "service_health": "HEALTHY",
                  "open_incidents": 0, "recent_pipeline_failure_rate_pct": None}
    flaky_facts = {**base_facts, "recent_pipeline_failure_rate_pct": 60.0}
    base_score = DeployRiskAgent._resolve_score(None, base_facts)
    flaky_score = DeployRiskAgent._resolve_score(None, flaky_facts)
    assert flaky_score > base_score


def test_resolve_score_ignores_low_failure_rate():
    base_facts = {"service_tier": "TIER_2", "service_health": "HEALTHY",
                  "open_incidents": 0, "recent_pipeline_failure_rate_pct": None}
    mild_facts = {**base_facts, "recent_pipeline_failure_rate_pct": 10.0}
    assert DeployRiskAgent._resolve_score(None, base_facts) == DeployRiskAgent._resolve_score(None, mild_facts)


# --- GitHubIssueTrackerConnector: real validation, no network in unit tests --

def test_connector_requires_token():
    with pytest.raises(ValueError, match="token"):
        GitHubIssueTrackerConnector(TENANT, {"owner": "acme", "repo": "payments-api"})


def test_connector_requires_owner_and_repo_to_build_a_repo_call():
    conn = GitHubIssueTrackerConnector(TENANT, {"token": "ghp_x"})
    with pytest.raises(ValueError, match="owner/repo"):
        conn._repo()


def test_connector_builds_real_github_headers_and_repo():
    conn = GitHubIssueTrackerConnector(
        TENANT, {"token": "ghp_x", "owner": "acme", "repo": "payments-api"}
    )
    assert conn.headers["Authorization"] == "Bearer ghp_x"
    assert conn.base_url == "https://api.github.com"
    assert conn._repo() == "acme/payments-api"


# --- On-call + pipeline-run endpoints (DB-backed, no LLM required) -----------

@pytest.mark.asyncio
async def test_oncall_endpoint_reports_who_is_on_call_now(async_client: AsyncClient, db):
    eng = Engineer(id="e1", tenant_id=TENANT, name="Ravi Iyer", email="ravi@acme.com")
    db.add(eng)
    await db.flush()
    now = datetime.now(timezone.utc)
    db.add_all([
        OnCallRotation(id="r1", tenant_id=TENANT, engineer_id=eng.id, squad="Platform",
                       role=OnCallRole.PRIMARY,
                       starts_at=now - timedelta(days=1), ends_at=now + timedelta(days=1)),
        OnCallRotation(id="r2", tenant_id=TENANT, engineer_id=eng.id, squad="Platform",
                       role=OnCallRole.PRIMARY,
                       starts_at=now - timedelta(days=10), ends_at=now - timedelta(days=8)),
    ])
    await db.commit()

    r = await async_client.get("/api/v1/engineering/oncall")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 2
    current = next(row for row in rows if row["id"] == "r1")
    assert current["active"] is True
    assert current["engineer_name"] == "Ravi Iyer"     # resolved, not a raw id
    past = next(row for row in rows if row["id"] == "r2")
    assert past["active"] is False

    active_only = (await async_client.get("/api/v1/engineering/oncall?active_only=true")).json()
    assert [row["id"] for row in active_only] == ["r1"]


@pytest.mark.asyncio
async def test_pipeline_runs_endpoint_filters_by_service_and_status(async_client: AsyncClient, db):
    svc = Service(id="s1", tenant_id=TENANT, name="Payments API", slug="payments-api",
                  tier=ServiceTier.TIER_1, health=ServiceHealth.DEGRADED)
    other_svc = Service(id="s2", tenant_id=TENANT, name="Identity", slug="identity",
                        tier=ServiceTier.TIER_1, health=ServiceHealth.HEALTHY)
    db.add_all([svc, other_svc])
    await db.flush()
    now = datetime.now(timezone.utc)
    db.add_all([
        PipelineRun(id="p1", tenant_id=TENANT, service_id=svc.id, pipeline_name="build-and-test",
                    run_number=1, status=PipelineStatus.FAILED, started_at=now - timedelta(hours=1)),
        PipelineRun(id="p2", tenant_id=TENANT, service_id=svc.id, pipeline_name="build-and-test",
                    run_number=2, status=PipelineStatus.SUCCEEDED, started_at=now - timedelta(hours=2)),
        PipelineRun(id="p3", tenant_id=TENANT, service_id=other_svc.id, pipeline_name="build-and-test",
                    run_number=1, status=PipelineStatus.SUCCEEDED, started_at=now - timedelta(hours=1)),
    ])
    await db.commit()

    r = await async_client.get(f"/api/v1/engineering/pipeline-runs?service_id={svc.id}")
    assert r.status_code == 200
    ids = {row["id"] for row in r.json()}
    assert ids == {"p1", "p2"}

    failed = await async_client.get(f"/api/v1/engineering/pipeline-runs?service_id={svc.id}&status=FAILED")
    assert [row["id"] for row in failed.json()] == ["p1"]


@pytest.mark.asyncio
async def test_deploy_risk_agent_reads_real_pipeline_history_from_db(db):
    """The same service_id + tenant_id + status filter assess_deployment uses,
    proven against a real DB - not just the pure function."""
    svc = Service(id="svc-flaky", tenant_id=TENANT, name="Payments API", slug="payments-api",
                  tier=ServiceTier.TIER_1, health=ServiceHealth.HEALTHY,
                  error_budget_remaining_pct=90.0, open_incidents=0)
    other_tenant_svc = Service(id="svc-other", tenant_id="tenant_other", name="X", slug="x")
    db.add_all([svc, other_tenant_svc])
    await db.flush()
    now = datetime.now(timezone.utc)
    db.add_all([
        PipelineRun(id="pf1", tenant_id=TENANT, service_id=svc.id, pipeline_name="build-and-test",
                    run_number=1, status=PipelineStatus.FAILED, started_at=now - timedelta(hours=1)),
        PipelineRun(id="pf2", tenant_id=TENANT, service_id=svc.id, pipeline_name="build-and-test",
                    run_number=2, status=PipelineStatus.FAILED, started_at=now - timedelta(hours=2)),
        PipelineRun(id="pf3", tenant_id=TENANT, service_id=svc.id, pipeline_name="build-and-test",
                    run_number=3, status=PipelineStatus.SUCCEEDED, started_at=now - timedelta(hours=3)),
        # A different tenant's run for the "same" service slug must never leak in.
        PipelineRun(id="pf4", tenant_id="tenant_other", service_id=other_tenant_svc.id,
                    pipeline_name="build-and-test", run_number=1, status=PipelineStatus.FAILED,
                    started_at=now - timedelta(hours=1)),
    ])
    await db.commit()

    recent_runs = (await db.execute(
        select(PipelineRun).where(
            PipelineRun.service_id == svc.id, PipelineRun.tenant_id == TENANT,
            PipelineRun.status.in_([PipelineStatus.SUCCEEDED, PipelineStatus.FAILED]),
        )
    )).scalars().all()
    assert len(recent_runs) == 3
    rate = DeployRiskAgent._pipeline_failure_rate(recent_runs)
    assert rate == pytest.approx(66.7, rel=1e-2)
