"""
KAEOS Engineering Domain — Database Seed Script

Seeds a realistic delivery org: a service catalog with SLO posture, engineers,
pull requests spanning the risk spectrum, deployments, and live incidents —
including one incident deliberately correlated with a recent deploy so the
incident agent has a real signal to find.
"""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone


from app.core.database import AsyncSessionLocal, async_engine
from app.core.domain_seed import SEED_TENANT as TENANT, already_seeded, new_id, run_standalone

from app.engineering.models.core import Engineer, Service, ServiceHealth, ServiceTier
from app.engineering.models.delivery import (
    Deployment, DeployStatus, PRStatus, PullRequest,
)
from app.engineering.models.incidents import (
    Incident, IncidentSeverity, IncidentStatus, Postmortem,
)
from app.engineering.models.ops import (
    OnCallRole, OnCallRotation, PipelineRun, PipelineStatus,
)


def _now():
    return datetime.now(timezone.utc)


async def seed_tenant(db, tenant: str) -> bool:
    if await already_seeded(db, "Engineering", Engineer, tenant):
        return False

    # ── Engineers ────────────────────────────────────────────────────────
    engineers = [
        Engineer(id=new_id(), tenant_id=tenant, name="Ravi Iyer", email="ravi.iyer@acme.com",
                 github_handle="raviiyer", squad="Platform", seniority="STAFF",
                 on_call=True, review_load=3),
        Engineer(id=new_id(), tenant_id=tenant, name="Dana Whitfield", email="dana.w@acme.com",
                 github_handle="danaw", squad="Payments", seniority="SENIOR",
                 on_call=False, review_load=2),
        Engineer(id=new_id(), tenant_id=tenant, name="Tomas Berg", email="tomas.berg@acme.com",
                 github_handle="tberg", squad="Platform", seniority="MID",
                 on_call=False, review_load=1),
        Engineer(id=new_id(), tenant_id=tenant, name="Priya Nandakumar", email="priya.n@acme.com",
                 github_handle="priyan", squad="Data", seniority="PRINCIPAL",
                 on_call=True, review_load=4),
    ]
    db.add_all(engineers)
    await db.flush()

    # ── Service catalog ──────────────────────────────────────────────────
    services = [
        Service(id=new_id(), tenant_id=tenant, name="Payments API", slug="payments-api",
                description="Handles card authorization, capture and refunds.",
                repo_url="https://github.com/acme/payments-api",
                tier=ServiceTier.TIER_1, health=ServiceHealth.DEGRADED,
                owning_squad="Payments", owner_engineer_id=engineers[1].id,
                slo_availability_target=99.95, slo_availability_actual=99.81,
                error_budget_remaining_pct=18.0, deploys_last_30d=14, open_incidents=1),
        Service(id=new_id(), tenant_id=tenant, name="Identity Service", slug="identity-service",
                description="Authentication, session management and SSO.",
                repo_url="https://github.com/acme/identity",
                tier=ServiceTier.TIER_1, health=ServiceHealth.HEALTHY,
                owning_squad="Platform", owner_engineer_id=engineers[0].id,
                slo_availability_target=99.95, slo_availability_actual=99.97,
                error_budget_remaining_pct=82.0, deploys_last_30d=6, open_incidents=0),
        Service(id=new_id(), tenant_id=tenant, name="Reporting Pipeline", slug="reporting-pipeline",
                description="Nightly ETL and customer-facing analytics.",
                repo_url="https://github.com/acme/reporting",
                tier=ServiceTier.TIER_2, health=ServiceHealth.HEALTHY,
                owning_squad="Data", owner_engineer_id=engineers[3].id,
                slo_availability_target=99.5, slo_availability_actual=99.62,
                error_budget_remaining_pct=64.0, deploys_last_30d=9, open_incidents=0),
        Service(id=new_id(), tenant_id=tenant, name="Internal Admin Console", slug="admin-console",
                description="Back-office tooling for support and finance staff.",
                repo_url="https://github.com/acme/admin-console",
                tier=ServiceTier.TIER_3, health=ServiceHealth.HEALTHY,
                owning_squad="Platform", owner_engineer_id=engineers[2].id,
                slo_availability_target=99.0, slo_availability_actual=99.4,
                error_budget_remaining_pct=91.0, deploys_last_30d=3, open_incidents=0),
    ]
    db.add_all(services)
    await db.flush()
    payments, identity, reporting, admin = services

    # ── Pull requests — deliberately spanning the risk spectrum ──────────
    prs = [
        # High risk: touches auth + migration, CI red, coverage drops.
        PullRequest(id=new_id(), tenant_id=tenant, service_id=identity.id, number=482,
                    title="Rotate session token signing keys",
                    description="Introduces key rotation for session JWTs and migrates the token store.",
                    author_id=engineers[0].id, branch="feat/key-rotation",
                    status=PRStatus.IN_REVIEW, additions=624, deletions=189, files_changed=23,
                    touches_migrations=True, touches_auth=True, test_coverage_delta=-3.4,
                    ci_passing=False, approvals=0),
        # Medium: large but safe.
        PullRequest(id=new_id(), tenant_id=tenant, service_id=reporting.id, number=311,
                    title="Parallelize nightly aggregation job",
                    description="Splits the nightly rollup across workers to cut runtime.",
                    author_id=engineers[3].id, branch="perf/parallel-rollup",
                    status=PRStatus.OPEN, additions=412, deletions=203, files_changed=11,
                    touches_migrations=False, touches_auth=False, test_coverage_delta=1.2,
                    ci_passing=True, approvals=1),
        # Low: tiny doc/config change.
        PullRequest(id=new_id(), tenant_id=tenant, service_id=admin.id, number=97,
                    title="Correct timezone label on export screen",
                    description="Fixes a mislabeled timezone in the CSV export header.",
                    author_id=engineers[2].id, branch="fix/tz-label",
                    status=PRStatus.APPROVED, additions=6, deletions=2, files_changed=1,
                    touches_migrations=False, touches_auth=False, test_coverage_delta=0.0,
                    ci_passing=True, approvals=2),
        # Merged, tied to the deploy that precedes the live incident.
        PullRequest(id=new_id(), tenant_id=tenant, service_id=payments.id, number=1204,
                    title="Add retry with backoff to acquirer client",
                    description="Retries transient acquirer failures; changes connection pooling.",
                    author_id=engineers[1].id, branch="fix/acquirer-retry",
                    status=PRStatus.MERGED, additions=147, deletions=38, files_changed=5,
                    touches_migrations=False, touches_auth=False, test_coverage_delta=0.8,
                    ci_passing=True, approvals=2,
                    merged_at=_now() - timedelta(hours=5)),
    ]
    db.add_all(prs)
    await db.flush()

    # ── Deployments ──────────────────────────────────────────────────────
    deploys = [
        # The suspect: shipped to a tier-1 service 4h before the incident.
        Deployment(id=new_id(), tenant_id=tenant, service_id=payments.id,
                   pull_request_id=prs[3].id, version="v2.14.0", environment="production",
                   status=DeployStatus.SUCCEEDED, deployed_by="dana.w@acme.com",
                   change_count=1, started_at=_now() - timedelta(hours=4),
                   completed_at=_now() - timedelta(hours=4) + timedelta(minutes=6),
                   duration_seconds=372),
        Deployment(id=new_id(), tenant_id=tenant, service_id=reporting.id,
                   version="v5.2.1", environment="production",
                   status=DeployStatus.SUCCEEDED, deployed_by="priya.n@acme.com",
                   change_count=3, started_at=_now() - timedelta(days=1),
                   completed_at=_now() - timedelta(days=1) + timedelta(minutes=11),
                   duration_seconds=655),
        Deployment(id=new_id(), tenant_id=tenant, service_id=identity.id,
                   version="v3.9.0", environment="production",
                   status=DeployStatus.ROLLED_BACK, deployed_by="ravi.iyer@acme.com",
                   change_count=2, is_rollback=True,
                   started_at=_now() - timedelta(days=3),
                   completed_at=_now() - timedelta(days=3) + timedelta(minutes=22),
                   duration_seconds=1320),
        # Awaiting the deploy-risk agent + human approval.
        Deployment(id=new_id(), tenant_id=tenant, service_id=payments.id,
                   version="v2.15.0-rc1", environment="production",
                   status=DeployStatus.PENDING_APPROVAL, deployed_by="dana.w@acme.com",
                   change_count=4, started_at=_now()),
    ]
    db.add_all(deploys)
    await db.flush()

    # ── Incidents ────────────────────────────────────────────────────────
    incidents = [
        # Live SEV2 on the degraded tier-1 service, right after v2.14.0.
        Incident(id=new_id(), tenant_id=tenant, service_id=payments.id,
                 incident_number="INC-2026-0042",
                 title="Elevated card authorization latency",
                 description=(
                     "p99 authorization latency rose from 240ms to 1.8s. Error rate at 2.3%. "
                     "Began roughly 30 minutes after the v2.14.0 rollout."
                 ),
                 severity=IncidentSeverity.SEV2, status=IncidentStatus.MITIGATING,
                 commander_id=engineers[1].id, detected_by="ALERT",
                 customer_impacting=True, affected_users=4200,
                 detected_at=_now() - timedelta(hours=3, minutes=30),
                 acknowledged_at=_now() - timedelta(hours=3, minutes=26),
                 time_to_acknowledge_mins=4),
        # Resolved, feeds MTTR.
        Incident(id=new_id(), tenant_id=tenant, service_id=reporting.id,
                 incident_number="INC-2026-0041",
                 title="Nightly report delivery delayed",
                 description="ETL job exceeded its window; customer reports delivered 2h late.",
                 severity=IncidentSeverity.SEV3, status=IncidentStatus.RESOLVED,
                 commander_id=engineers[3].id, detected_by="CUSTOMER",
                 customer_impacting=True, affected_users=85,
                 detected_at=_now() - timedelta(days=2),
                 resolved_at=_now() - timedelta(days=2) + timedelta(minutes=95),
                 time_to_acknowledge_mins=12, time_to_resolve_mins=95),
        # Resolved sev1 with a postmortem due.
        Incident(id=new_id(), tenant_id=tenant, service_id=identity.id,
                 incident_number="INC-2026-0039",
                 title="Login outage following v3.9.0",
                 description="Session validation rejected all tokens after deploy; rolled back.",
                 severity=IncidentSeverity.SEV1, status=IncidentStatus.POSTMORTEM_DUE,
                 commander_id=engineers[0].id, detected_by="ALERT",
                 customer_impacting=True, affected_users=18500,
                 suspected_deployment_id=deploys[2].id,
                 detected_at=_now() - timedelta(days=3),
                 resolved_at=_now() - timedelta(days=3) + timedelta(minutes=41),
                 time_to_acknowledge_mins=2, time_to_resolve_mins=41),
    ]
    db.add_all(incidents)
    await db.flush()

    db.add(Postmortem(
        id=new_id(), tenant_id=tenant, incident_id=incidents[2].id,
        summary="A signing-key mismatch in v3.9.0 invalidated every active session.",
        root_cause=(
            "The new key was published to the config store but the validator still read the "
            "old key path, so all tokens failed verification."
        ),
        contributing_factors=[
            "No staging soak covered token validation against a rotated key.",
            "Rollout was not canaried; 100% of traffic shifted at once.",
        ],
        action_items=[
            {"action": "Add key-rotation integration test to CI", "owner": "ravi.iyer@acme.com",
             "due": str((_now() + timedelta(days=7)).date()), "done": False},
            {"action": "Require canary stage for all TIER_1 deploys", "owner": "dana.w@acme.com",
             "due": str((_now() + timedelta(days=14)).date()), "done": False},
        ],
        published=True,
    ))

    # ── On-call rotations — current + one upcoming shift per squad, plus a
    #    completed prior shift so the history isn't just a single row ─────
    rotations = [
        OnCallRotation(id=new_id(), tenant_id=tenant, engineer_id=engineers[0].id,
                        squad="Platform", role=OnCallRole.PRIMARY,
                        starts_at=_now() - timedelta(days=2), ends_at=_now() + timedelta(days=5)),
        OnCallRotation(id=new_id(), tenant_id=tenant, engineer_id=engineers[2].id,
                        squad="Platform", role=OnCallRole.SECONDARY,
                        starts_at=_now() - timedelta(days=2), ends_at=_now() + timedelta(days=5)),
        OnCallRotation(id=new_id(), tenant_id=tenant, engineer_id=engineers[3].id,
                        squad="Data", role=OnCallRole.PRIMARY,
                        starts_at=_now() - timedelta(days=1), ends_at=_now() + timedelta(days=6)),
        OnCallRotation(id=new_id(), tenant_id=tenant, engineer_id=engineers[1].id,
                        squad="Payments", role=OnCallRole.PRIMARY,
                        starts_at=_now() + timedelta(days=5), ends_at=_now() + timedelta(days=12)),
        OnCallRotation(id=new_id(), tenant_id=tenant, engineer_id=engineers[0].id,
                        squad="Platform", role=OnCallRole.PRIMARY,
                        starts_at=_now() - timedelta(days=9), ends_at=_now() - timedelta(days=2)),
    ]
    db.add_all(rotations)

    # ── CI pipeline runs — real build/test history behind the deploy-risk
    #    agent's score, not just a single PR's ci_passing flag. Payments is
    #    deliberately flaky (matches its DEGRADED health + open incident);
    #    identity and reporting are clean. ─────────────────────────────────
    pipeline_runs = []
    run_specs = [
        # (service, pr, name, statuses-newest-first, branch)
        (payments, prs[3], "build-and-test",
         [(PipelineStatus.SUCCEEDED, 812, 0), (PipelineStatus.FAILED, 795, 17),
          (PipelineStatus.SUCCEEDED, 803, 0), (PipelineStatus.FAILED, 780, 9),
          (PipelineStatus.SUCCEEDED, 790, 0)], "fix/acquirer-retry"),
        (identity, prs[0], "build-and-test",
         [(PipelineStatus.FAILED, 411, 6), (PipelineStatus.SUCCEEDED, 402, 0),
          (PipelineStatus.SUCCEEDED, 398, 0)], "feat/key-rotation"),
        (reporting, prs[1], "build-and-test",
         [(PipelineStatus.SUCCEEDED, 266, 0), (PipelineStatus.SUCCEEDED, 260, 0),
          (PipelineStatus.SUCCEEDED, 255, 0)], "perf/parallel-rollup"),
    ]
    hours_ago = 1
    for service, pr, name, runs, branch in run_specs:
        for status, run_number, tests_failed in runs:
            hours_ago += 6
            started = _now() - timedelta(hours=hours_ago)
            pipeline_runs.append(PipelineRun(
                id=new_id(), tenant_id=tenant, service_id=service.id, pull_request_id=pr.id,
                pipeline_name=name, run_number=run_number, status=status,
                trigger="PULL_REQUEST", branch=branch,
                commit_sha=uuid.uuid4().hex[:12],
                tests_passed=140 - tests_failed, tests_failed=tests_failed,
                duration_seconds=310 if status == PipelineStatus.SUCCEEDED else 96,
                started_at=started,
                completed_at=started + timedelta(minutes=5 if status == PipelineStatus.SUCCEEDED else 2),
            ))
    db.add_all(pipeline_runs)

    await db.commit()
    print(f"[EngineeringSeed] {len(services)} services, {len(engineers)} engineers, "
          f"{len(prs)} PRs, {len(deploys)} deployments, {len(incidents)} incidents seeded, "
          f"{len(rotations)} on-call rotations, {len(pipeline_runs)} pipeline runs.")
    return True


async def seed(tenant: str | None = None) -> bool:
    return await run_standalone(async_engine, AsyncSessionLocal, seed_tenant, tenant or TENANT)


if __name__ == "__main__":
    asyncio.run(seed())
