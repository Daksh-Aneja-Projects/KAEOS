import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, and_
from datetime import datetime, timezone
from typing import Optional
from app.core.config import get_settings
from app.core.database import MaintenanceSessionLocal
from app.models.domain import Rule
from app.services.metrics_timeseries import run_metrics_rollup

logger = logging.getLogger(__name__)

_BATCH_LIMIT = 500

# Last-run heartbeat for every scheduled job, keyed by name -> {ok, at, error}.
# Exposed via GET /ops/scheduler so an operator can see a job that dies every tick
# while /health and /status stay green. Populated by _tracked below.
# ponytail: in-process dict on the leader only; aggregate across replicas via a
# shared store (Redis/DB) if multi-worker heartbeat visibility is ever needed.
_LAST_RUN: dict[str, dict] = {}


async def _tracked(name: str, fn) -> None:
    """Run a scheduled coroutine-function ``fn`` and record its outcome in _LAST_RUN.

    NOTE: most jobs catch and log their own exceptions, so they return normally and
    record ok=True (a heartbeat/last-run timestamp is still the point). A job that
    lets an exception propagate is recorded ok=False with the error, which is what
    makes an every-tick failure visible instead of silent.
    """
    at = datetime.now(timezone.utc).isoformat()
    try:
        await fn()
        _LAST_RUN[name] = {"ok": True, "at": at, "error": None}
    except Exception as e:
        _LAST_RUN[name] = {"ok": False, "at": at, "error": str(e)[:500]}
        logger.error("[Scheduler] job %s raised: %s", name, e)


def _is_leader() -> bool:
    """Belt-and-suspenders: only the elected leader runs scheduled jobs.

    The leader is normally the only replica that even starts the scheduler, but
    this guard closes the brief window after a lost lease and makes every job
    safe to schedule everywhere.
    """
    try:
        from app.services.leader_lock import leader_lock
        return leader_lock.is_leader
    except Exception:
        return True   # no leader machinery → single instance → proceed


async def run_decay_checks():
    """Background task to check rule freshness and trigger decay.

    Uses the maintenance (owner) session so it bypasses RLS — this is a
    cross-tenant housekeeping job that must see all tenants' rules.
    Only processes rules that are active, validated, and have a half-life.
    """
    if not _is_leader():
        return
    logger.info("[Scheduler] Running background decay check...")
    try:
        async with MaintenanceSessionLocal() as db:
            now = datetime.now(timezone.utc)
            res = await db.execute(
                select(Rule)
                .where(
                    and_(
                        Rule.is_archived == False,
                        Rule.validated_at.isnot(None),
                        Rule.half_life_days > 0,
                    )
                )
                .limit(_BATCH_LIMIT)
            )
            rules = res.scalars().all()

            decay_count = 0
            for rule in rules:
                days_since = (now - rule.validated_at.replace(tzinfo=timezone.utc)).days
                if days_since > rule.half_life_days:
                    decay_factor = days_since // rule.half_life_days
                    new_conf = max(0.1, rule.confidence_scalar * (0.9 ** decay_factor))

                    if new_conf < rule.confidence_scalar:
                        rule.confidence_scalar = new_conf
                        decay_count += 1

            if decay_count > 0:
                await db.commit()
                logger.info(f"[Scheduler] Decayed {decay_count} rules due to age.")
            else:
                logger.info("[Scheduler] No rules required decay.")
    except Exception as e:
        logger.error(f"[Scheduler] Decay check failed: {e}")


async def run_retention_sweep():
    """Enforce configured data-retention windows across every tenant.

    Opt-in per tenant/data-class (see app/services/retention.py). Leader-guarded
    and idempotent — deleting rows already gone is a no-op — so an accidental
    double-run wastes work but never corrupts. Runs on the owner session via
    ``sweep_all_tenants`` which iterates tenants under each one's RLS context.
    """
    if not _is_leader():
        return
    logger.info("[Scheduler] Running data-retention sweep...")
    try:
        from app.services import retention
        receipts = await retention.sweep_all_tenants(dry_run=False)
        purged = sum(r.get("total", 0) for r in receipts if isinstance(r, dict))
        logger.info("[Scheduler] Retention sweep purged %d rows across %d tenants",
                    purged, len(receipts))
    except Exception as e:
        logger.error(f"[Scheduler] Retention sweep failed: {e}")


async def run_foundry_mining():
    """Continuously curate governed executions into training examples (AI Foundry).

    Makes "continuously improve" real: instead of an operator manually POSTing
    /foundry/datasets/build, the dataset grows on a cadence from every tenant's
    governed executions. Leader-guarded and idempotent (already-mined executions
    carry source='mined' and are skipped), so a double-run is safe. Promotion of
    any resulting model stays HUMAN-gated - this only fills the funnel.
    """
    if not _is_leader():
        return
    logger.info("[Scheduler] Running AI Foundry dataset mining...")
    try:
        from app.services.foundry import dataset_builder
        from app.models.domain import SkillExecution
        async with MaintenanceSessionLocal() as db:
            tenant_ids = (await db.execute(
                select(SkillExecution.tenant_id).distinct()
            )).scalars().all()
            total, tenants = 0, 0
            for tid in tenant_ids:
                if not tid:
                    continue
                tenants += 1
                result = await dataset_builder.mine_executions(db, tid)
                total += int(result.get("created", 0) or 0)
            logger.info(
                "[Scheduler] Foundry mining curated %d new example(s) across %d tenant(s)",
                total, tenants,
            )
    except Exception as e:
        logger.error(f"[Scheduler] Foundry mining failed: {e}")


async def run_job_queue():
    """Drain the durable job queue (leader-guarded).

    Replaces fire-and-forget ``asyncio.create_task`` for long-running work: jobs
    are persisted before execution, so nothing is lost on a worker crash. The
    processor itself is leader-guarded inside ``process_jobs``.
    """
    try:
        from app.services import job_queue
        result = await job_queue.process_jobs()
        if result.get("succeeded") or result.get("failed") or result.get("retried"):
            logger.info("[Scheduler] Job queue drained: %s", result)
    except Exception as e:
        logger.error(f"[Scheduler] Job queue processing failed: {e}")


async def run_job_queue_reaper():
    """Requeue durable jobs a crashed worker left RUNNING (at-least-once)."""
    try:
        from app.services import job_queue
        recovered = await job_queue.requeue_stuck_jobs()
        if recovered:
            logger.info("[Scheduler] Job queue reaper recovered %d job(s)", len(recovered))
    except Exception as e:
        logger.error(f"[Scheduler] Job queue reaper failed: {e}")


async def run_finetune_poll():
    """L2: poll external fine-tune jobs to completion and auto-trigger eval.

    Leader-guarded, cross-tenant (owner session). Promotion of any resulting
    winner stays human-gated — this only advances the bridge and fills the funnel.
    """
    if not _is_leader():
        return
    try:
        from app.services.foundry import finetune
        async with MaintenanceSessionLocal() as db:
            result = await finetune.poll_finetune_jobs(db)
        if result.get("advanced"):
            logger.info("[Scheduler] Fine-tune bridge advanced %d job(s)", result["advanced"])
    except Exception as e:
        logger.error(f"[Scheduler] Fine-tune poll failed: {e}")


async def run_autonomy_governor_job():
    """L5-reverse: nudge each tenant's per-domain autonomy dial from the measured
    safe-autonomy-rate (bounded; respects human-set dials). Leader-guarded."""
    if not _is_leader():
        return
    try:
        from app.services.autonomy_governor import run_autonomy_governor
        from app.models.domain import SkillExecution
        async with MaintenanceSessionLocal() as db:
            tenant_ids = (await db.execute(
                select(SkillExecution.tenant_id).distinct()
            )).scalars().all()
            adjusted = 0
            for tid in tenant_ids:
                if not tid:
                    continue
                receipt = await run_autonomy_governor(db, tid)
                adjusted += receipt.get("adjusted", 0)
            if adjusted:
                logger.info("[Scheduler] Autonomy governor adjusted %d domain dial(s)", adjusted)
    except Exception as e:
        logger.error(f"[Scheduler] Autonomy governor failed: {e}")


async def run_drift_detection_job():
    """DETECTION ONLY: find systems-of-record rows that changed outside the
    actuation path and raise an ExternalSignal so a human sees them.

    Deliberately does NOT reconcile. Writing back to a system of record is a
    governed action that belongs behind the 7 gates with a human in the loop;
    a background sweep silently re-applying state would be exactly the kind of
    ungoverned autonomy this platform exists to prevent. Leader-guarded.
    """
    if not _is_leader():
        return
    try:
        from app.models.actuation import SorObject
        from app.models.event_mesh import ExternalSignal
        from app.services.actuation import Actuator
        async with MaintenanceSessionLocal() as db:
            tenant_ids = (await db.execute(
                select(SorObject.tenant_id).distinct()
            )).scalars().all()
            flagged = resolved = refreshed = 0
            for tid in tenant_ids:
                if not tid:
                    continue
                report = await Actuator.compute_drift(db, tenant_id=tid)
                drifted = report.get("drift") or []
                # The single OPEN drift signal for this tenant, if any. One open
                # at a time keeps the operator from drowning in duplicates - but
                # it must have a lifecycle, or the first detection silences drift
                # forever (the guard below would never clear).
                open_sig = (await db.execute(
                    select(ExternalSignal).where(
                        ExternalSignal.tenant_id == tid,
                        ExternalSignal.kind == "DRIFT",
                        ExternalSignal.status != "RESOLVED",
                    ).order_by(ExternalSignal.created_at.desc()).limit(1)
                )).scalar_one_or_none()

                if not drifted:
                    # Drift cleared (reconciled by a human, or the SoR reverted):
                    # close the open signal so the NEXT real drift can raise a
                    # fresh one. Without this, drift fires exactly once per tenant.
                    if open_sig is not None:
                        open_sig.status = "RESOLVED"
                        open_sig.responded_at = datetime.now(timezone.utc)
                        resolved += 1
                    continue

                names = ", ".join(
                    f"{d.get('system')}:{d.get('external_id')}" for d in drifted[:5])
                body = (f"These systems-of-record rows no longer match the last "
                        f"governed action KAEOS took on them: {names}"
                        f"{' and others' if len(drifted) > 5 else ''}. "
                        f"Nothing was changed automatically; review and reconcile.")
                severity = "warning" if len(drifted) < 10 else "critical"
                if open_sig is not None:
                    # Same condition still open - refresh it in place so the
                    # operator sees the CURRENT drift set (it may have grown),
                    # rather than a stale count or a pile of duplicates.
                    open_sig.title = f"{len(drifted)} record(s) changed outside KAEOS"
                    open_sig.body = body
                    open_sig.severity = severity
                    open_sig.matched_entities = drifted[:20]
                    refreshed += 1
                    continue
                db.add(ExternalSignal(
                    tenant_id=tid, kind="DRIFT",
                    title=f"{len(drifted)} record(s) changed outside KAEOS",
                    body=body,
                    source="drift-monitor",
                    severity=severity,
                    matched_entities=drifted[:20],
                    status="NEW",
                ))
                flagged += 1
            if flagged or resolved or refreshed:
                await db.commit()
                logger.info(
                    "[Scheduler] Drift detection: %d raised, %d refreshed, %d resolved",
                    flagged, refreshed, resolved)
    except Exception as e:
        logger.error(f"[Scheduler] Drift detection failed: {e}")


async def run_deployment_reaper():
    """Recover deployments orphaned by a crashed/restarted worker.

    The deployment pipeline is a fire-and-forget task; if its worker dies the row
    hangs in a non-terminal state. This leader-guarded sweep transitions stuck
    deployments to FAILED so they surface instead of hanging forever.
    """
    if not _is_leader():
        return
    try:
        from app.workforce.deployment.studio import DeploymentStudio
        async with MaintenanceSessionLocal() as db:
            recovered = await DeploymentStudio.recover_orphaned_deployments(db)
        if recovered:
            logger.info("[Scheduler] Deployment reaper recovered %d orphaned deployment(s)", len(recovered))
    except Exception as e:
        logger.error(f"[Scheduler] Deployment reaper failed: {e}")


async def run_weekly_digest():
    """Leader-guarded: deliver the executive digest to every active tenant."""
    if not _is_leader():
        return
    try:
        from app.services.digest import send_weekly_digest
        result = await send_weekly_digest()
        logger.info("[Scheduler] weekly digest: %s", result)
    except Exception as e:
        logger.error(f"[Scheduler] weekly digest failed: {e}")


async def run_outbound_sync_dispatch():
    """Leader-guarded: deliver queued outbound write-backs to external systems."""
    if not _is_leader():
        return
    try:
        from app.services.sync_engine import dispatch_outbound
        result = await dispatch_outbound()
        if result.get("sent") or result.get("failed") or result.get("dead"):
            logger.info("[Scheduler] outbound sync: %s", result)
    except Exception as e:
        logger.error(f"[Scheduler] outbound sync dispatch failed: {e}")


# How many connectors one pull pass will touch. Real HTTP + inference per
# connector, so an unbounded sweep on a large install is a self-inflicted load
# spike; the rest are picked up on the next tick.
# ponytail: flat cap, upgrade to a per-connector due-time (sync_frequency) if a
# large install needs different cadences per connector.
_PULL_CONNECTOR_LIMIT = 25


def _max_watermark(records: list) -> Optional[str]:
    """Highest source-reported ``updated_at`` across fetched records, or None.

    The delta cursor advances from the DATA - the newest update timestamp the
    source itself reported - never from KAEOS's wall clock, so skew / timezone
    drift between KAEOS and the source cannot silently drop records. ServiceNow
    watermarks are fixed-width ``YYYY-MM-DD HH:MM:SS``, so a lexical max is the
    chronological max. Only adapters that surface ``updated_at`` (ServiceNow
    today) advance a cursor; the rest return None here and keep their cursor.
    """
    return max((r.get("updated_at") for r in records
                if isinstance(r, dict) and r.get("updated_at")), default=None)


async def run_connector_pull_sync():
    """Leader-guarded pull: fetch recent records from every credentialed
    CONNECTED connector and dedup them into the twin (natural-key upsert, so a
    re-pull updates in place instead of duplicating).

    True incremental delta today is ServiceNow-only: it advances a persisted
    cursor from its own ``sys_updated_on`` high-water mark, so the next pass
    fetches only what changed since. Every other adapter pulls its most-recently-
    updated window (bounded by ``batch_size``) each pass and does NOT advance a
    cursor - an honest fixed-window pull, not a false delta promise.

    Per-connector isolation: one unreachable source fails only its own row.
    """
    if not _is_leader():
        return
    from app.core.context import current_tenant_id
    from app.core.database import AsyncSessionLocal
    from app.models.domain import Connector, ConnectorCredential
    from app.services.live_connectors import LiveConnectorService, decrypt_secrets

    async with MaintenanceSessionLocal() as mdb:
        rows = (await mdb.execute(
            select(Connector, ConnectorCredential)
            .join(ConnectorCredential, ConnectorCredential.connector_id == Connector.id)
            .where(Connector.status == "CONNECTED")
            .limit(_PULL_CONNECTOR_LIMIT)
        )).all()
        targets = [(c.id, c.tenant_id, c.name, c.sync_cursor,
                    cred.provider, dict(cred.config or {}), cred.secrets_encrypted)
                   for c, cred in rows]

    synced = 0
    for cid, tid, name, cursor, provider, config, enc in targets:
        started = datetime.now(timezone.utc)
        token = current_tenant_id.set(tid)
        try:
            async with AsyncSessionLocal() as db:
                secrets = decrypt_secrets(enc)
                records = await LiveConnectorService.fetch_records(
                    provider, {**config, "_cursor": cursor}, secrets)
                # Advance the delta cursor from the DATA, not KAEOS's wall clock:
                # the watermark is the newest source-reported update timestamp we
                # actually saw, so skew / timezone drift between KAEOS and the
                # source can no longer silently drop records. Only ServiceNow
                # surfaces one today; every other provider returns None here and
                # keeps its prior cursor (see the run_connector_pull_sync docs).
                watermark = _max_watermark(records)
                signals = LiveConnectorService.records_to_signals(records, tid, name)
                stats = await LiveConnectorService.persist_signals(db, signals)
                conn = (await db.execute(
                    select(Connector).where(Connector.id == cid))).scalar_one_or_none()
                if conn is not None:
                    conn.events_ingested = (conn.events_ingested or 0) + len(records)
                    conn.signals_extracted = (conn.signals_extracted or 0) + stats["inserted"]
                    conn.last_sync_at = started
                    if watermark:
                        conn.sync_cursor = watermark
                await db.commit()
                if stats["inserted"] or stats["updated"]:
                    synced += 1
        except Exception as e:
            logger.warning("[Scheduler] pull sync connector %s failed: %s", cid, e)
        finally:
            current_tenant_id.reset(token)
    if synced:
        logger.info("[Scheduler] pull sync updated %d connector(s)", synced)


# How many tenants one warming pass will generate reports for. The work is real
# model inference, so an unbounded sweep on a large install would be a
# self-inflicted load spike; the rest are warmed on the next pass, or on demand.
_WARM_TENANT_LIMIT = 5


async def run_benchmark_warmup():
    """Pre-compute the two expensive benchmark analyses so nobody waits for them.

    Both are cached against the org's rule count, skill count and average
    confidence, so this only does real work when a tenant's numbers have
    actually moved since the last pass; otherwise the cache already holds the
    answer and the call returns immediately. That is what makes running this on
    a cadence cheap rather than wasteful.

    It calls the same builders the endpoints call, deliberately: a warmer with
    its own copy of the prompt would compute a different fingerprint and warm a
    key no request ever reads. Leader-guarded, so one replica does the inference.
    """
    if not _is_leader():
        return
    try:
        from app.api.routes.benchmark import build_cross_org_benchmark, build_intelligence_report
        from app.models.domain import Skill

        async with MaintenanceSessionLocal() as db:
            tenant_ids = [
                t for t in (await db.execute(select(Skill.tenant_id).distinct())).scalars().all() if t
            ][:_WARM_TENANT_LIMIT]
            for tid in tenant_ids:
                try:
                    await build_cross_org_benchmark(db, tid)
                    await build_intelligence_report(db, tid)
                except Exception:
                    # One tenant's model failure must not stop the others.
                    logger.warning("[Scheduler] Benchmark warmup failed for %s", tid, exc_info=True)
            if tenant_ids:
                logger.info("[Scheduler] Benchmark cache warm for %d tenant(s)", len(tenant_ids))
    except Exception as e:
        logger.error(f"[Scheduler] Benchmark warmup failed: {e}")


async def run_audit_checkpoints():
    """Anchor each tenant's recent audit-log window into the signed ledger.

    Windowed digests (see app/core/audit.py): a later deletion or edit of
    audit rows inside an anchored window is detectable against the append-only
    provenance chain. Leader-guarded; owner session so every tenant is swept.
    """
    if not _is_leader():
        return
    try:
        from sqlalchemy import select

        from app.core.audit import checkpoint_audit_log
        from app.core.context import current_tenant_id
        from app.core.database import MaintenanceSessionLocal
        from app.models.domain import SecurityAuditLog

        async with MaintenanceSessionLocal() as db:
            tenants = (await db.execute(
                select(SecurityAuditLog.tenant_id).distinct()
            )).scalars().all()
        anchored = 0
        for t in tenants:
            if not t:
                continue
            current_tenant_id.set(t)
            async with MaintenanceSessionLocal() as db:
                if await checkpoint_audit_log(db, t):
                    anchored += 1
        if anchored:
            logger.info("[Scheduler] Anchored audit checkpoints for %d tenant(s)", anchored)
    except Exception as e:
        logger.error(f"[Scheduler] Audit checkpointing failed: {e}")


async def run_usage_metering():
    """Leader-guarded: rate each tenant's current-period governed executions and
    push the overage to the billing provider (no-op self-host).

    Per-tenant RLS context is set before each tenant's rating so the execution
    count and report upsert stay tenant-isolated on Postgres. Idempotent: the
    report is keyed on (tenant, period) and the provider push uses action=set,
    so an overlapping run reports the same total instead of double-billing.
    """
    if not _is_leader():
        return
    from app.core.context import current_tenant_id
    from app.core.database import AsyncSessionLocal
    from app.models.domain import SkillExecution
    from app.services.usage_rating import record_and_report

    async with MaintenanceSessionLocal() as mdb:
        tenant_ids = [t for t in (await mdb.execute(
            select(SkillExecution.tenant_id).distinct()
        )).scalars().all() if t]

    rated = 0
    for tid in tenant_ids:
        token = current_tenant_id.set(tid)
        try:
            async with AsyncSessionLocal() as db:
                await record_and_report(db, tid)
                rated += 1
        except Exception as e:
            logger.warning("[Scheduler] usage metering failed for %s: %s", tid, e)
        finally:
            current_tenant_id.reset(token)
    if rated:
        logger.info("[Scheduler] usage metering rated %d tenant(s)", rated)


# A mission RUNNING with no ledger event newer than this is presumed abandoned by
# a crashed/restarted worker (its in-process runner + _RUNNING_MISSIONS guard were
# wiped). Above the step-level _STEP_STALE_AFTER (10 min) so we only re-kick truly
# stalled missions, never one that is mid-step.
_MISSION_STALE_AFTER_MINUTES = 15


async def run_mission_reaper():
    """Re-invoke missions left RUNNING by a crashed worker.

    ``start_mission_run`` is only called from the missions route and ``_RUNNING_MISSIONS``
    is in-process (wiped on restart), so a mission that was RUNNING when the worker
    died never advances again; the step-level ``_recover_stale`` only runs once
    ``advance_mission`` is called, which nothing does. This leader-guarded sweep finds
    RUNNING missions whose most recent ledger event is older than the threshold and
    re-kicks ``start_mission_run`` (idempotent via ``_RUNNING_MISSIONS``; the step-level
    FOR UPDATE SKIP LOCKED claim prevents any double governed execution). Mission has no
    ``updated_at`` column, so the max ``MissionEvent.created_at`` is the freshness signal.
    """
    if not _is_leader():
        return
    from datetime import timedelta

    from sqlalchemy import func as safunc

    from app.core.context import current_tenant_id
    from app.models.missions import Mission, MissionEvent
    from app.services.missions import engine as missions

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=_MISSION_STALE_AFTER_MINUTES)
    try:
        async with MaintenanceSessionLocal() as db:
            rows = (await db.execute(
                select(Mission.tenant_id, Mission.id, safunc.max(MissionEvent.created_at))
                .join(MissionEvent, MissionEvent.mission_id == Mission.id)
                .where(Mission.status == "RUNNING")
                .group_by(Mission.id, Mission.tenant_id)
            )).all()
        stale = []
        for tid, mid, last in rows:
            if last is None:
                continue
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            if last < cutoff:
                stale.append((tid, mid))
        # Set the tenant contextvar before start_mission_run: it spawns the runner
        # via asyncio.create_task, which snapshots the current context, so the
        # background runner inherits the right tenant for its RLS-enforced session.
        for tid, mid in stale:
            token = current_tenant_id.set(tid)
            try:
                await missions.start_mission_run(tid, mid)
            finally:
                current_tenant_id.reset(token)
        if stale:
            logger.info("[Scheduler] mission reaper re-invoked %d stalled mission(s)", len(stale))
    except Exception as e:
        logger.error(f"[Scheduler] mission reaper failed: {e}")


async def run_accrual_reaper():
    """Book approved-but-unaccrued AP invoices that lazy retry left off the ledger.

    ``accrue_invoice`` is called inline when an invoice is approved/paid, but a
    transient failure (or approval before the accrual hook existed) can leave an
    APPROVED invoice with no AP_ACCRUAL journal entry - a real liability missing
    from the P&L and balance sheet. This leader-guarded sweep finds every APPROVED
    invoice lacking a POSTED AP_ACCRUAL entry and accrues it. accrue_invoice is
    idempotent (guarded by the same existing-entry SELECT), so a double-run never
    double-posts. Owner session, cross-tenant; accrue_invoice/_find_account are
    parameterized by tenant_id, so no RLS context is required.
    """
    if not _is_leader():
        return
    from app.finance.models.accounts_payable import Invoice, InvoiceStatus
    from app.finance.models.core import JournalEntry, JournalEntryStatus
    from app.finance.services.payments import accrue_invoice

    try:
        async with MaintenanceSessionLocal() as db:
            accrued_exists = select(JournalEntry.id).where(
                JournalEntry.source_module == "AP_ACCRUAL",
                JournalEntry.source_document_id == Invoice.id,
                JournalEntry.tenant_id == Invoice.tenant_id,
                JournalEntry.status == JournalEntryStatus.POSTED,
            )
            invoices = (await db.execute(
                select(Invoice)
                .where(Invoice.status == InvoiceStatus.APPROVED, ~accrued_exists.exists())
                .limit(_BATCH_LIMIT)
            )).scalars().all()
            booked = 0
            for inv in invoices:
                try:
                    entry = await accrue_invoice(db, inv.tenant_id, inv, actor="accrual_reaper")
                    if entry is not None:
                        await db.commit()
                        booked += 1
                    else:
                        await db.rollback()  # zero-amount invoice: nothing to post
                except Exception as e:
                    await db.rollback()
                    logger.error("[Scheduler] accrual reaper failed for invoice %s: %s",
                                 inv.id, e)
            if booked:
                logger.info("[Scheduler] accrual reaper booked %d unaccrued invoice(s)", booked)
    except Exception as e:
        logger.error(f"[Scheduler] accrual reaper failed: {e}")


def init_scheduler() -> AsyncIOScheduler:
    # Register durable-job handlers before the processor can tick.
    try:
        from app.services.job_handlers import register_all
        register_all()
    except Exception as e:
        logger.error(f"[Scheduler] Failed to register job handlers: {e}")

    scheduler = AsyncIOScheduler()
    # Every job runs through _tracked(name, fn) so its last-run/last-success/error is
    # recorded in _LAST_RUN and visible at GET /ops/scheduler. args=[name, fn] feed the
    # wrapper; the trigger + id/coalesce/max_instances kwargs are unchanged.
    scheduler.add_job(
        _tracked, 'interval', minutes=60, args=['decay_checks', run_decay_checks],
        id='decay_checks_job', replace_existing=True
    )
    # Durable job queue: drain due jobs frequently (deployments start within a
    # tick), and reap jobs a crashed worker left RUNNING.
    scheduler.add_job(
        _tracked, 'interval', seconds=15, args=['job_queue', run_job_queue],
        id='job_queue_job', replace_existing=True, max_instances=1, coalesce=True,
    )
    scheduler.add_job(
        _tracked, 'interval', minutes=5, args=['job_queue_reaper', run_job_queue_reaper],
        id='job_queue_reaper_job', replace_existing=True
    )
    # Re-invoke missions left RUNNING by a crashed worker (in-process runner state is
    # wiped on restart). Idempotent; the step-level row claim prevents double-run.
    scheduler.add_job(
        _tracked, 'interval', minutes=5, args=['mission_reaper', run_mission_reaper],
        id='mission_reaper_job', replace_existing=True, max_instances=1, coalesce=True,
    )
    # Bidirectional sync: push queued governed mutations out to connected
    # external systems every minute (inbound is realtime via webhooks; this is
    # the outbound half plus retry of transient failures).
    scheduler.add_job(
        _tracked, 'interval', minutes=1, args=['outbound_sync', run_outbound_sync_dispatch],
        id='outbound_sync_job', replace_existing=True, max_instances=1, coalesce=True,
    )
    # Inbound pull half: incremental delta pull from credentialed connectors on
    # an interval (real-time connectors push via webhooks; this catches systems
    # that cannot push, and backfills what a missed webhook dropped).
    scheduler.add_job(
        _tracked, 'interval', minutes=5, args=['connector_pull_sync', run_connector_pull_sync],
        id='connector_pull_sync_job', replace_existing=True, max_instances=1, coalesce=True,
    )
    # Executive digest: Monday 08:00 in the server's timezone. Tenants without
    # a subscribed notification channel simply receive nothing.
    scheduler.add_job(
        _tracked, 'cron', day_of_week='mon', hour=8, minute=0, args=['weekly_digest', run_weekly_digest],
        id='weekly_digest_job', replace_existing=True, max_instances=1, coalesce=True,
    )
    # Retention enforcement runs daily — windows are day-granular, so an hourly
    # sweep would be pure churn. Only tenants that opted a data class in are touched.
    scheduler.add_job(
        _tracked, 'interval', hours=24, args=['retention_sweep', run_retention_sweep],
        id='retention_sweep_job', replace_existing=True
    )
    # Audit tamper-evidence: anchor each tenant's recent audit window into the
    # signed provenance ledger every 12h (windows are 24h, so consecutive
    # checkpoints overlap and no row goes unanchored).
    scheduler.add_job(
        _tracked, 'interval', hours=12, args=['audit_checkpoints', run_audit_checkpoints],
        id='audit_checkpoint_job', replace_existing=True, max_instances=1, coalesce=True,
    )
    # AI Foundry: mine governed executions into training examples on a cadence so
    # the improvement loop is continuous, not manual. Promotion stays human-gated.
    scheduler.add_job(
        _tracked, 'interval', hours=6, args=['foundry_mining', run_foundry_mining],
        id='foundry_mining_job', replace_existing=True
    )
    # L5-reverse autonomy governor: adapt per-domain dials from the measured
    # safe-autonomy-rate on a cadence (bounded nudges; human-set dials untouched).
    scheduler.add_job(
        _tracked, 'interval', hours=6, args=['autonomy_governor', run_autonomy_governor_job],
        id='autonomy_governor_job', replace_existing=True
    )
    # Drift detection: flag systems-of-record rows changed outside the actuation
    # path. Detection only - reconciliation stays a human-gated governed action.
    scheduler.add_job(
        _tracked, 'interval', hours=1, args=['drift_detection', run_drift_detection_job],
        id='drift_detection_job', replace_existing=True, max_instances=1, coalesce=True,
    )
    # Keep the two expensive benchmark analyses warm so opening the lane is
    # instant instead of a ~30s wait. A pass is nearly free when the org numbers
    # have not moved, because the cache already answers. max_instances=1 so a
    # slow pass never overlaps itself and doubles the model load.
    scheduler.add_job(
        _tracked, 'interval', minutes=30, args=['benchmark_warmup', run_benchmark_warmup],
        id='benchmark_warmup_job', replace_existing=True, max_instances=1, coalesce=True,
    )
    # L2 fine-tune bridge: poll external jobs to completion + auto-eval (5 min).
    scheduler.add_job(
        _tracked, 'interval', minutes=5, args=['finetune_poll', run_finetune_poll],
        id='finetune_poll_job', replace_existing=True
    )
    # Recover deployments orphaned by a worker crash/restart (fire-and-forget
    # pipeline has no durable queue yet); frequent + cheap.
    scheduler.add_job(
        _tracked, 'interval', minutes=15, args=['deployment_reaper', run_deployment_reaper],
        id='deployment_reaper_job', replace_existing=True
    )
    # Usage metering: rate governed executions per tenant and push overage to the
    # billing provider (no-op self-host). Hourly is ample — Stripe bills on the
    # period total (action=set), so cadence only affects freshness, not amount.
    scheduler.add_job(
        _tracked, 'interval', hours=1, args=['usage_metering', run_usage_metering],
        id='usage_metering_job', replace_existing=True, max_instances=1, coalesce=True,
    )
    # Time-series metrics rollup: snapshot each tenant's current-hour safe-autonomy
    # rate / cost / execution volume into ts_metric_samples so Time Machine and
    # dashboards read a stored series. Idempotent per (tenant, metric, hour bucket),
    # so hourly cadence with coalesce means at most one row per bucket.
    scheduler.add_job(
        _tracked, 'interval',
        minutes=int(getattr(get_settings(), "METRICS_ROLLUP_INTERVAL_MINUTES", 60)),
        args=['metrics_rollup', run_metrics_rollup],
        id='metrics_rollup_job', replace_existing=True, max_instances=1, coalesce=True,
    )
    # Accrual reaper: book APPROVED invoices that inline accrual retry never
    # reached, so no liability sits off-books. Idempotent (accrue_invoice guards
    # on the existing AP_ACCRUAL entry), so hourly re-runs never double-post.
    scheduler.add_job(
        _tracked, 'interval', hours=1, args=['accrual_reaper', run_accrual_reaper],
        id='accrual_reaper_job', replace_existing=True, max_instances=1, coalesce=True,
    )
    return scheduler


if __name__ == "__main__":
    # Self-check for the delta-cursor watermark: lexical max == chronological max
    # for fixed-width ServiceNow timestamps, missing/blank timestamps are skipped,
    # and an empty batch yields None (so the cursor is left untouched, not blanked).
    assert _max_watermark([]) is None
    assert _max_watermark([{"external_id": "1"}, {"updated_at": None}]) is None
    assert _max_watermark([
        {"updated_at": "2026-08-16 09:00:00"},
        {"updated_at": "2026-08-16 11:30:00"},
        {"updated_at": "2026-08-16 09:59:59"},
        {"no_ts": True},
    ]) == "2026-08-16 11:30:00"
    print("scheduler _max_watermark self-check ok")

    # _tracked records ok=True on success and ok=False + error on a throwing coro.
    import asyncio as _asyncio

    async def _ok():
        return None

    async def _boom():
        raise RuntimeError("nope")

    _asyncio.run(_tracked("t_ok", _ok))
    assert _LAST_RUN["t_ok"]["ok"] is True and _LAST_RUN["t_ok"]["error"] is None
    _asyncio.run(_tracked("t_boom", _boom))
    assert _LAST_RUN["t_boom"]["ok"] is False and "nope" in _LAST_RUN["t_boom"]["error"]
    print("scheduler _tracked self-check ok")
