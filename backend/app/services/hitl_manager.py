import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any

from sqlalchemy import select, update

# S6 M8.3 - hoisted out of the method bodies; all cycle-free from here and all
# at or below this layer. Two imports deliberately STAY in-function below:
#   - app.api.routes.approvals (approval_links) points UP into the API layer,
#     which the M8.2 layering tripwire forbids at top level;
#   - app.agents.runtime (AgentExecutor) would pull the whole gate stack -
#     executor, debate, fairness, actuation, llm_router - into every module
#     that touches HITL, and it is reached once per human approval.
from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.core.metrics import HITL_REQUESTS, HITL_RESOLUTIONS
from app.core.redis import get_redis
from app.models.agent_factory import ActivityEventType, ActivitySeverity
from app.models.domain import Skill, SkillExecution
from app.models.execution_status import AgentState, ExecutionStatus
from app.models.notifications import NotificationChannel
from app.services import job_queue
# Imported as a MODULE, not as the bare function: the notifier is substituted by
# attribute (monkeypatch.setattr(notifier, "notify_fire_and_forget", ...)) in the
# HITL suites, because its fire-and-forget task opens a second session on the
# in-memory StaticPool's single shared connection and an interleaved ROLLBACK
# silently undoes the resolve transaction. A `from ... import` binding here would
# snapshot the real function and make that substitution a no-op.
from app.services import notifier
from app.services.activity_feed import ActivityFeedService
from app.services.compliance import ComplianceEngine
from app.services.live_connectors import decrypt_secrets

logger = logging.getLogger(__name__)

# Redis key prefix for HITL pending approvals (survives restarts)
_HITL_KEY_PREFIX = "kaeos:hitl:"
# Per-tenant SET of the exec ids that are PENDING, so /hitl/pending is O(pending)
# instead of O(whole keyspace). Deliberately NOT under "kaeos:hitl:": the record
# MATCH pattern is "kaeos:hitl:*", and an index key under that prefix would be
# returned by the backfill SCAN and by any other reader of the record prefix,
# which would then try to json.loads() a Redis set. A disjoint prefix makes that
# impossible by construction instead of by a remember-to-skip check.
_HITL_INDEX_PREFIX = "kaeos:hitlidx:"
# TTL: 24 hours (86400 seconds)
_HITL_TTL = 86400
# The durable resume backstop fires this long after approval. Long enough that
# a legitimate slow resume (local-model steps run minutes) has finished - the
# handler no-ops on terminal rows - short enough that a crashed resume is
# recovered the same morning it was approved.
RESUME_BACKSTOP_SECONDS = 600


class HITLManager:
    """
    Manages Human-in-the-Loop workflows for agent executions.

    NON-BLOCKING PATTERN:
    1. request_human_confirmation() stores the pending record and returns immediately
    2. Frontend polls GET /hitl/status/{id} for decision updates
    3. When human approves via POST /hitl/{id}/approve, a background task resumes execution

    Pending approvals are stored in Redis so they survive server restarts and work
    across multiple worker processes.
    """

    def __init__(self):
        # In-memory fallback when Redis is unavailable (single-instance only).
        # The old code logged "falling back to in-memory storage" but stored
        # nothing - every Gate-3 pause was announced yet unactionable.
        self._memory: Dict[str, Dict[str, Any]] = {}
        # Mirrors the Redis TTL for the fallback store: without it, a Redis
        # outage under load grew _memory one record per HITL pause, forever.
        self._memory_expiry: Dict[str, float] = {}
        # One backfill SCAN per process, not per empty index: an index set with
        # no members does not exist in Redis, so an EXISTS check alone would
        # re-scan on every poll for every tenant with nothing pending - which is
        # the common case and the exact cost this change removes.
        self._index_backfilled = False

    def _redis_key(self, exec_id: str) -> str:
        return f"{_HITL_KEY_PREFIX}{exec_id}"

    def _index_key(self, tenant_id: str) -> str:
        return f"{_HITL_INDEX_PREFIX}{tenant_id}"

    async def _index_add(self, redis, tenant_id: str, exec_id: str) -> None:
        key = self._index_key(tenant_id)
        await redis.sadd(key, exec_id)
        # Refreshed on every add so the index outlives its newest record.
        await redis.expire(key, _HITL_TTL)

    async def _index_discard(self, redis, tenant_id: str, exec_id: str) -> None:
        await redis.srem(self._index_key(tenant_id), exec_id)

    @staticmethod
    def _json_safe(d: Dict[str, Any]) -> Dict[str, Any]:
        """Copy of a dict with private keys dropped and values JSON-coerced."""
        out = {}
        for k, v in (d or {}).items():
            if str(k).startswith("_"):
                continue
            try:
                json.dumps(v)
                out[k] = v
            except (TypeError, ValueError):
                out[k] = str(v)
        return out

    async def _get_redis(self):
        """Return the Redis client if available, else None."""
        try:
            # Call the accessor rather than importing the module global: the
            # global is rebound on (re)connect, and a `from ... import
            # redis_client` binding is a snapshot taken at first call.
            return await get_redis()
        except Exception:
            # Redis is optional; without it HITL falls back to DB-only state.
            return None

    async def request_human_confirmation(self, skill: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """Non-blocking: Store pending approval and return immediately with execution_id."""
        exec_id = context.get("execution_id")
        if not exec_id:
            logger.error("No execution ID provided for HITL")
            return {"approved": None, "pending": True, "execution_id": None, "reason": "System error: No execution_id"}

        try:
            HITL_REQUESTS.inc()
        except Exception:
            pass

        logger.info(f"[HITL] Approval required for execution {exec_id} — returning immediately (non-blocking)")

        # Emit an event to the activity feed
        feed = ActivityFeedService()
        tenant_id = context.get("tenant_id", "default")

        await feed.emit(
            event_type=ActivityEventType.HITL_REQUIRED,
            title=f"Approval Required: {skill.get('skill_id', 'unknown')}",
            description="Agent paused due to low confidence or Tier-1 policy.",
            tenant_id=tenant_id,
            severity=ActivitySeverity.ACTION_REQUIRED,
            source_type="execution",
            source_id=exec_id,
            requires_action=True,
        )

        # Persist pending approval in Redis (immediately)
        redis = await self._get_redis()
        pending_data = {
            "exec_id": exec_id,
            "skill_id": skill.get("skill_id", "unknown"),
            "tenant_id": tenant_id,
            "status": "PENDING",
            "decision": None,
            "approver": None,
            "reason": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            # Enough to resume gated (synthetic-skill) executions that have no
            # SkillExecution row yet: the skill contract and a JSON-safe context.
            "skill_def": {
                "skill_id": skill.get("skill_id", "unknown"),
                # The compiled Skill row id, when the pause came from a
                # persisted skill: lets the resume rebuild the full contract
                # even after this cache record expires.
                "skill_db_id": skill.get("skill_db_id"),
                "steps": skill.get("steps", []),
                "compliance_tags": skill.get("compliance_tags", []),
                "department": skill.get("department", "general"),
                # A paused governed WRITE (e.g. the /actuation consequence
                # gate) carries its intent so approval actually applies it.
                "actuation": skill.get("actuation"),
            },
            "context": self._json_safe(context),
        }

        if not redis:
            logger.warning("[HITL] Redis unavailable — using in-memory HITL store (single-instance only)")
        # One write path, so the pending index is maintained in exactly one place.
        await self._put_record(exec_id, pending_data)

        # The DATABASE is the source of truth for pending approvals: every
        # Gate-3 pause gets a PENDING_HITL SkillExecution row, so the single
        # /skills/hitl queue lists all approvals and they survive restarts.
        # The Redis/memory record above is a cache carrying the resume payload.
        try:
            async with AsyncSessionLocal() as session:
                existing = (await session.execute(
                    select(SkillExecution).where(SkillExecution.id == exec_id)
                )).scalar_one_or_none()
                if existing:
                    existing.agent_state = AgentState.PAUSED
                    existing.hitl_required = True
                    if not existing.status:
                        existing.status = ExecutionStatus.PENDING_HITL
                else:
                    session.add(SkillExecution(
                        id=exec_id,
                        skill_db_id=skill.get("skill_db_id"),
                        skill_id_name=skill.get("skill_id", "unknown"),
                        tenant_id=tenant_id,
                        status=ExecutionStatus.PENDING_HITL,
                        route_type="GATED_AGENT",
                        agent_state=AgentState.PAUSED,
                        task_intent=str(
                            context.get("intent")
                            or context.get("instruction")
                            or skill.get("skill_id", "")
                        )[:500],
                        context=self._json_safe(context),
                        reasoning_chain=[],
                        hitl_required=True,
                    ))
                await session.commit()
        except Exception as e:
            logger.warning(f"[HITL] Could not persist PENDING_HITL row: {e}")

        # Reach the approver where they live (email/Slack/webhook), not just the
        # in-app queue - a governance loop that pauses silently stalls autonomy.
        # Scheduled AFTER the pause is durably persisted: never announce an
        # approval that is not yet in the queue.
        # KEPT in-function (M8.3): app.api.routes.approvals is the API layer,
        # and app/services may not import it at top level (M8.2 tripwire).
        from app.api.routes.approvals import approval_links
        base = get_settings().PUBLIC_BASE_URL or "http://localhost:8001"
        subject = f"KAEOS approval needed: {skill.get('skill_id', 'unknown')}"

        def _body(links: Dict[str, Any]) -> str:
            lines = (f"\nApprove: {links['approve']}\nReject:  {links['reject']}\n"
                     if links else "")
            return (f"A governed execution paused for human approval.\n"
                    f"Skill: {skill.get('skill_id', 'unknown')}\n"
                    f"Department: {skill.get('department', 'general')}\n"
                    f"Execution: {exec_id}\n"
                    f"{lines}"
                    f"Or review it in KAEOS under My Work.")

        def _mint(recipient: str | None) -> Dict[str, Any]:
            # One-click decide links (signed, single-purpose, 7-day TTL) so an
            # approver in email/Slack never has to log in. `recipient` becomes
            # the token subject: a real, attributable identity that satisfies
            # SOX four-eyes. None falls back to the non-attributable
            # 'email-approver' subject, which check_sox BLOCKS for financial
            # writes (fail-closed) - an anonymous link can never clear SoD.
            try:
                return approval_links(exec_id, tenant_id, base, recipient=recipient,
                                      department=skill.get("department"))
            except Exception:
                logger.warning("HITL approval-link build failed for exec %s",
                               exec_id, exc_info=True)
                return {}

        # Mint one link set PER real recipient under their own identity, and
        # deliver it to them - so the emailed link a specific human clicks is
        # attributable to that human, not a shared constant.
        recipients = await self._resolve_notification_recipients(tenant_id)
        if recipients:
            # ponytail: slack/webhook channels (which have no single human
            # identity) receive one copy per recipient. Acceptable - governance
            # alerts are at-least-once; upgrade path is per-recipient link
            # minting inside notifier.notify()'s channel fan-out.
            for addr in recipients:
                links = _mint(addr)
                notifier.notify_fire_and_forget(
                    tenant_id, "hitl.pending", subject=subject, body=_body(links),
                    data={"execution_id": exec_id, "skill_id": skill.get("skill_id"),
                          **({"approval_links": links} if links else {})},
                    to_override=[addr],
                )
        else:
            # No resolvable recipient identity: single notification with a
            # fail-closed, non-attributable link set.
            links = _mint(None)
            notifier.notify_fire_and_forget(
                tenant_id, "hitl.pending", subject=subject, body=_body(links),
                data={"execution_id": exec_id, "skill_id": skill.get("skill_id"),
                      **({"approval_links": links} if links else {})},
            )

        # Return immediately with execution_id so caller can poll or subscribe for updates
        return {
            "approved": None,
            "pending": True,
            "execution_id": exec_id,
            "reason": "Awaiting human approval",
        }

    async def _resolve_notification_recipients(self, tenant_id: str) -> list[str]:
        """The real email identities the hitl.pending one-click links reach.

        Reads the tenant's enabled SMTP notification channels subscribed to
        hitl.pending and returns their to_addrs, de-duplicated in order. Each
        becomes the token subject of that recipient's approval link, so a click
        is attributable to a real human (SOX four-eyes). SMTP is the only
        channel kind with an individual human address; Slack/webhook are group
        targets with no single principal, so they are deliberately excluded.

        Never raises: on any error returns [] and the caller falls back to a
        single non-attributable, fail-closed link set.
        """
        try:
            async with AsyncSessionLocal() as db:
                channels = (await db.execute(
                    select(NotificationChannel).where(
                        NotificationChannel.tenant_id == tenant_id,
                        NotificationChannel.kind == "smtp",
                        NotificationChannel.enabled.is_(True),
                    )
                )).scalars().all()
            addrs: list[str] = []
            seen: set[str] = set()
            for ch in channels:
                events = ch.events or []
                if events and "hitl.pending" not in events:
                    continue
                try:
                    cfg = decrypt_secrets(ch.config_encrypted)
                except Exception:
                    continue
                to = cfg.get("to_addrs") or []
                if isinstance(to, str):
                    to = [to]
                for a in to:
                    if a and a not in seen:
                        seen.add(a)
                        addrs.append(a)
            return addrs
        except Exception:
            logger.warning("[HITL] recipient resolution failed for %s",
                           tenant_id, exc_info=True)
            return []

    async def _get_record(self, execution_id: str) -> Dict[str, Any] | None:
        """Fetch a HITL record from Redis, falling back to the memory store."""
        redis = await self._get_redis()
        if redis:
            raw = await redis.get(self._redis_key(execution_id))
            if raw:
                return json.loads(raw)
        return self._memory.get(execution_id)

    async def _put_record(self, execution_id: str, data: Dict[str, Any], ttl: int = _HITL_TTL):
        redis = await self._get_redis()
        if redis:
            # Record key and JSON are unchanged, so a rolling deploy where old
            # workers still read these records keeps working.
            await redis.setex(self._redis_key(execution_id), ttl, json.dumps(data))
            tenant_id = data.get("tenant_id")
            if tenant_id:
                if data.get("status") == "PENDING":
                    await self._index_add(redis, tenant_id, execution_id)
                else:
                    # Resolved (or any non-pending state): leaves the queue here,
                    # so list_pending never has to read it to find that out.
                    await self._index_discard(redis, tenant_id, execution_id)
        else:
            import time
            now = time.time()
            self._memory[execution_id] = data
            self._memory_expiry[execution_id] = now + ttl
            # Amortized prune (same lifetime Redis enforces via setex).
            for k in [k for k, exp in self._memory_expiry.items() if exp < now]:
                self._memory.pop(k, None)
                self._memory_expiry.pop(k, None)

    async def get_record_department(self, execution_id: str) -> str | None:
        """The department of a pending approval's skill (for scope checks)."""
        record = await self._get_record(execution_id)
        if not record:
            return None
        return (record.get("skill_def") or {}).get("department")

    async def _backfill_index(self, redis) -> None:
        """Rebuild the per-tenant indexes from the records, once per process.

        Records written before this index existed (or by an old worker mid
        rolling deploy) have no index entry, and the frontend must not lose
        sight of a pending approval because of a deploy. One bounded SCAN pass
        - never KEYS, which blocks the whole server for the length of the
        keyspace - reconstructs them.
        """
        cursor = 0
        while True:
            cursor, keys = await redis.scan(
                cursor, match=f"{_HITL_KEY_PREFIX}*", count=200
            )
            for key, raw in zip(keys, await redis.mget(keys) if keys else []):
                try:
                    data = json.loads(raw) if raw else None
                except ValueError:
                    continue
                if not data or data.get("status") != "PENDING":
                    continue
                owner = data.get("tenant_id")
                if owner:
                    await self._index_add(redis, owner, key[len(_HITL_KEY_PREFIX):])
            if int(cursor) == 0:
                return

    async def list_pending(self, tenant_id: str) -> list:
        """All PENDING approvals for a tenant, from Redis or the memory store.

        Reads the tenant's pending index and MGETs those records: one round
        trip, O(that tenant's pending approvals). It used to KEYS the whole
        keyspace and GET every match, per poll, per open browser tab.
        """
        pending = []
        redis = await self._get_redis()
        if redis:
            try:
                idx = self._index_key(tenant_id)
                if not self._index_backfilled:
                    if not await redis.exists(idx):
                        await self._backfill_index(redis)
                    # ponytail: one backfill per process. A record written by a
                    # DRAINING old worker after this worker backfilled stays
                    # unindexed until it resolves or expires - it is still in
                    # the DB-backed queue (/skills/hitl/pending) and still
                    # resolvable by id, only this Redis listing misses it.
                    # Upgrade path if that window ever matters: re-arm the flag
                    # on a timer instead of a bool, trading one bounded SCAN per
                    # interval for it.
                    self._index_backfilled = True
                exec_ids = list(await redis.smembers(idx))
                raws = await redis.mget(
                    [self._redis_key(i) for i in exec_ids]) if exec_ids else []
                stale = []
                for exec_id, raw in zip(exec_ids, raws):
                    data = json.loads(raw) if raw else None
                    # Belt and braces on tenant_id: the index says whose it is,
                    # the record proves it.
                    if (data and data.get("status") == "PENDING"
                            and data.get("tenant_id") == tenant_id):
                        pending.append(data)
                    else:
                        # Record expired, or resolved by a path that could not
                        # update the index - self-heal so it converges.
                        stale.append(exec_id)
                if stale:
                    await redis.srem(idx, *stale)
            except Exception as e:
                logger.warning(f"[HITL] Redis pending-index read failed: {e}")
        for data in self._memory.values():
            if data.get("tenant_id") == tenant_id and data.get("status") == "PENDING":
                pending.append(data)
        return pending

    async def get_hitl_status(
        self, execution_id: str, tenant_id: str | None = None
    ) -> Dict[str, Any]:
        """Get current status of a HITL approval (for polling).

        Pass the caller's tenant from any request path: keyed on execution_id
        alone this returned another tenant's approval record (approver, reason,
        decision). A foreign record answers NOT_FOUND - identical to a record
        that never existed, so ids cannot be probed across tenants.
        """
        data = await self._get_record(execution_id)
        if data and tenant_id is not None and data.get("tenant_id") != tenant_id:
            data = None
        if data:
            return {
                "execution_id": execution_id,
                "status": data.get("status", "UNKNOWN"),
                "decision": data.get("decision"),
                "approver": data.get("approver"),
                "reason": data.get("reason", ""),
                "created_at": data.get("created_at"),
            }

        # Not found (expired or never existed)
        return {
            "execution_id": execution_id,
            "status": "NOT_FOUND",
            "decision": None,
            "reason": "Execution not found or expired",
        }

    async def resolve_hitl(
        self,
        execution_id: str,
        approved: bool,
        approver: str = "human",
        reason: str = "",
        tenant_id: str | None = None,
    ) -> bool:
        """Resolve a pending HITL approval and schedule the resume.

        `tenant_id` is the caller's tenant and MUST be passed by any request-
        driven path. This looked the record up by execution_id alone, so one
        tenant could approve — and thereby RESUME — another tenant's gated
        agent action. That is the governance guarantee the product is sold on,
        so it is checked here rather than trusted to callers.

        HITL records live in Redis, and SkillExecution is reachable by id, so
        row-level security cannot backstop this: the check below is the only
        thing enforcing it. None means "internal caller, already authorized"
        (the agent runtime resolving its own gate) - request handlers always
        pass a real tenant.
        """
        record = await self._get_record(execution_id)

        if tenant_id is not None:
            owner = None
            if record:
                owner = record.get("tenant_id")
            else:
                # Cache expired/absent: fall back to the DB row's tenant.
                async with AsyncSessionLocal() as session:
                    owner_q = await session.execute(
                        select(SkillExecution.tenant_id).where(
                            SkillExecution.id == execution_id
                        )
                    )
                    owner = owner_q.scalar_one_or_none()
            if owner is not None and owner != tenant_id:
                # Same answer as "not found": telling the caller it exists but
                # belongs to someone else confirms other tenants' execution ids.
                logger.warning(
                    f"[HITL] tenant {tenant_id} tried to resolve {execution_id} "
                    f"owned by {owner} - denied"
                )
                return False

        try:
            HITL_RESOLUTIONS.labels(decision="approved" if approved else "rejected").inc()
        except Exception:
            pass

        if record:
            record["status"] = "RESOLVED"
            record["decision"] = approved
            record["approver"] = approver
            record["reason"] = reason
            record["resolved_at"] = datetime.now(timezone.utc).isoformat()
            await self._put_record(execution_id, record, ttl=300)  # keep 5 min for reader
            logger.info(f"[HITL] Resolved {execution_id}: approved={approved}")
        else:
            # No cache record (e.g. a /skills-route pause, or the cache
            # expired) - the DB row below is still resolvable.
            logger.info(f"[HITL] No cache record for {execution_id}; resolving DB row only")

        # Update the DB row when one exists. Gate-3 pauses of gated (synthetic)
        # skills have no SkillExecution row yet - that is not an error; the
        # resume path below creates one via the executor.
        # Use optimistic locking to prevent double-resolution races.
        async with AsyncSessionLocal() as session:
            exec_q = await session.execute(
                select(SkillExecution).where(SkillExecution.id == execution_id)
            )
            execution = exec_q.scalar_one_or_none()
            # Capture the owning tenant as a plain string while the row is still
            # attached — used by the event-bus emit after the session closes.
            _ev_tenant = (execution.tenant_id if execution
                          else (record or {}).get("tenant_id")) or tenant_id
            if execution:
                if execution.agent_state not in (AgentState.PENDING_HITL, AgentState.PAUSED, None):
                    logger.warning(
                        f"[HITL] {execution_id} already resolved "
                        f"(state={execution.agent_state}) — ignoring duplicate"
                    )
                    return False
                # A rejection is terminal: finalize the row here so it leaves
                # the PENDING_HITL queue no matter which surface decided it
                # (the email-link path has no route-level finalizer). An
                # approval only transitions to RUNNING - the resumed executor
                # stamps the real final status when the run completes.
                values = dict(
                    agent_state=AgentState.RUNNING if approved else AgentState.FAILED,
                    hitl_approved=approved,
                    hitl_approver=approver,
                )
                if not approved:
                    values.update(
                        status=ExecutionStatus.HUMAN_OVERRIDDEN,
                        outcome_type=ExecutionStatus.HUMAN_OVERRIDDEN,
                        completed_at=datetime.now(timezone.utc),
                    )
                result = await session.execute(
                    update(SkillExecution)
                    .where(
                        SkillExecution.id == execution_id,
                        SkillExecution.agent_state.in_(
                            [AgentState.PENDING_HITL, AgentState.PAUSED, None]),
                    )
                    .values(**values)
                )
                if result.rowcount == 0:
                    logger.warning(f"[HITL] {execution_id} resolve lost CAS race — already handled")
                    return False

            if approved and (record or execution):
                # DURABLE resume: the backstop job commits ATOMICALLY with the
                # approval CAS above (same session), so there is no crash
                # window where a human approved work that then silently never
                # runs. The job fires only after RESUME_BACKSTOP_SECONDS; if
                # the immediate in-process resume below finished by then (the
                # normal case), the handler sees a terminal row and no-ops -
                # at-least-once, idempotent on execution_id.
                try:
                    _job_tenant = ((record or {}).get("tenant_id")
                                   or (execution.tenant_id if execution else None)
                                   or "default")
                    await job_queue.enqueue(
                        session, _job_tenant, "hitl_resume",
                        {"execution_id": execution_id,
                         "fallback_record": record if record else None},
                        max_attempts=3,
                        delay_seconds=RESUME_BACKSTOP_SECONDS,
                    )  # enqueue commits: CAS + job land together
                except Exception as e:
                    # The backstop failing must not block the approval itself -
                    # commit the CAS alone and fall back to the in-process task.
                    logger.error(f"[HITL] could not enqueue durable resume for "
                                 f"{execution_id}: {e}")
                    await session.commit()
            else:
                await session.commit()

        if not record and not execution:
            logger.warning(f"[HITL] {execution_id} unknown in cache and DB - nothing to resolve")
            return False

        # Immediate in-process resume for latency; the durable job above is
        # the crash-safety net, not the primary path.
        if approved:
            asyncio.create_task(self._resume_from_hitl(execution_id, fallback_record=record))

        # H8: publish the human decision onto the internal event bus (SystemEvent
        # + webhooks + WS + internal automations). Non-fatal — a bus hiccup must
        # never unwind a resolution that already committed above.
        if _ev_tenant:
            try:
                from app.services.event_bus import event_bus, EventType
                await event_bus.emit(
                    EventType.HITL_APPROVED if approved else EventType.HITL_REJECTED,
                    {"execution_id": execution_id, "approver": approver,
                     "reason": reason, "approved": approved},
                    tenant_id=_ev_tenant,
                )
            except Exception as e:
                logger.debug(f"[HITL] event-bus emit skipped: {e}")

        return True

    async def discard_pending(self, execution_id: str, tenant_id: str | None = None,
                              reason: str = "resolved via mission") -> bool:
        """Retire a pending HITL record WITHOUT resuming it (H11).

        A mission step's Gate-3 pause creates a HITL record keyed by that run's
        execution id, but the mission re-runs the approved step under a FRESH
        execution id (engine mints a new one each advance). So the paused run's
        record would otherwise linger in both the /hitl list and the DB-backed
        /skills/hitl queue as an orphaned, still-approvable entry. This retires it
        in lockstep with the mission-side resolution. Tenant-scoped; no resume.
        """
        record = await self._get_record(execution_id)
        if (tenant_id is not None and record
                and record.get("tenant_id") not in (None, tenant_id)):
            return False
        if record:
            record["status"] = "RESOLVED"
            record["reason"] = reason
            record["resolved_at"] = datetime.now(timezone.utc).isoformat()
            # status != PENDING -> list_pending self-heals it out of the index.
            await self._put_record(execution_id, record, ttl=60)
        # Finalize the DB PENDING_HITL row so it also leaves the /skills/hitl queue.
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(SkillExecution)
                .where(SkillExecution.id == execution_id,
                       SkillExecution.agent_state.in_(
                           [AgentState.PENDING_HITL, AgentState.PAUSED, None]))
                .values(agent_state=AgentState.FAILED,
                        status=ExecutionStatus.HUMAN_OVERRIDDEN,
                        outcome_type=ExecutionStatus.HUMAN_OVERRIDDEN,
                        completed_at=datetime.now(timezone.utc))
            )
            await session.commit()
        return True

    async def _resume_from_hitl(self, execution_id: str, fallback_record: Dict[str, Any] | None = None) -> bool:
        """Resume an approved execution through the full gate pipeline.

        Runs as the immediate in-process task AND as the durable ``hitl_resume``
        job's handler, so it is IDEMPOTENT on execution_id: a terminal row is a
        successful no-op. Returns True when the resume is handled (ran, or was
        already handled), False when it could not run (caller may retry).
        """
        logger.info(f"[HITL] Resuming execution {execution_id} post-approval")
        # Idempotency guard: the at-least-once backstop means this can run
        # after (or even while) another attempt handled the same approval.
        async with AsyncSessionLocal() as session:
            row = (await session.execute(
                select(SkillExecution).where(SkillExecution.id == execution_id)
            )).scalar_one_or_none()
            if row is not None and (
                row.completed_at is not None
                or (row.agent_state in (AgentState.COMPLETED, AgentState.FAILED)
                    # FAILED_RESUME means a previous ATTEMPT died, not that the
                    # decision reached a terminal outcome - retry those.
                    and row.status != ExecutionStatus.FAILED_RESUME)
            ):
                logger.info(f"[HITL] {execution_id} already finalized "
                            f"({row.agent_state}/{row.status}); resume is a no-op")
                return True
        try:
            # 1. Load execution record and the associated compiled Skill from the DB
            async with AsyncSessionLocal() as session:
                exec_q = await session.execute(
                    select(SkillExecution).where(SkillExecution.id == execution_id)
                )
                execution = exec_q.scalar_one_or_none()

                skill_obj = None
                if execution and execution.skill_db_id:
                    skill_q = await session.execute(
                        select(Skill).where(Skill.id == execution.skill_db_id)
                    )
                    skill_obj = skill_q.scalar_one_or_none()

            if execution:
                context = execution.context or {}
                tenant_id = execution.tenant_id
                skill_id_name = execution.skill_id_name or "unknown"
            elif fallback_record and fallback_record.get("skill_def", {}).get("steps"):
                # Gated (synthetic) skills pause at Gate 3 before any row is
                # persisted - the pending record carries the skill contract and
                # context, so approval still results in a real execution.
                logger.info(f"[HITL] No DB row for {execution_id}; resuming from pending record")
                context = dict(fallback_record.get("context") or {})
                tenant_id = fallback_record.get("tenant_id", "default")
                skill_id_name = fallback_record.get("skill_id", "unknown")
            else:
                logger.error(f"[HITL] Cannot resume {execution_id} — execution record not found")
                return False

            # 2. Build the skill dict for the executor
            if skill_obj:
                skill_def = {
                    "skill_id": skill_obj.skill_id,
                    "skill_db_id": skill_obj.id,
                    "department": skill_obj.department,
                    "steps": skill_obj.steps or [],
                    "compliance_tags": skill_obj.compliance_tags or [],
                    "guardrails": skill_obj.guardrails or {},
                }
            elif fallback_record and fallback_record.get("skill_def", {}).get("steps"):
                # Gated (synthetic) skills have a PENDING_HITL row but no
                # compiled Skill record - the pending record carries the contract.
                skill_def = dict(fallback_record["skill_def"])
            else:
                # Fallback: trivial single-step skill so the execution completes cleanly
                logger.warning(f"[HITL] Skill record missing for {execution_id}, running trivial resume")
                skill_def = {
                    "skill_id": skill_id_name,
                    "steps": [{"id": "resume_step", "action": "log", "prompt": "HITL approved — no further steps required."}],
                    "compliance_tags": [],
                    "guardrails": {},
                }

            # A paused governed WRITE rides its intent in the gate cache, with
            # the durable DB-row context as fallback for expired caches. It is
            # attached to the skill contract so runtime Gate 5b (the one
            # actuation gate) performs it fail-closed after every other gate.
            _act = ((fallback_record or {}).get("skill_def") or {}).get("actuation") \
                or (context or {}).get("actuation")
            if isinstance(_act, dict) and _act and not skill_def.get("actuation"):
                skill_def["actuation"] = _act

            # 3. Resume through the ONE gate pipeline (AgentExecutor), not a
            # bare SkillExecutionEngine. The old re-entry at Gate 5 skipped
            # fairness, audit and governed actuation on exactly the executions
            # a human had just approved. hitl_pre_approved=True satisfies
            # Gate 3 (the human gate has been passed - that is what this
            # resume IS); compliance and fairness still run, because a human
            # approval does not waive statutory checks.
            context["hitl_approved"] = True
            context["execution_id"] = execution_id
            context["tenant_id"] = tenant_id
            # The real approver identity, for the SOX has-human-approver check
            # and for actuation attribution. Server-derived from the resolved
            # execution row, never from client input.
            _approver = (execution.hitl_approver if execution else None) or "human-approver"
            context["has_human_approver"] = _approver
            # Four-eyes (SoD): attribute BOTH sides on resume. The approver is the
            # human who cleared this pause; the maker is the initiator carried on
            # the persisted context (its requester/creator), never the approver.
            # check_sox fails closed if they cannot be told apart, so a person
            # cannot approve their own financial write-back.
            context["approver"] = _approver
            context.setdefault(
                "maker", context.get("maker") or context.get("requested_by")
                or context.get("created_by")
            )
            if skill_obj is not None:
                context["_skill_obj"] = skill_obj

            # KEPT in-function (M8.3): app.agents.runtime pulls the entire gate
            # stack (executor, debate, fairness, actuation, llm_router) at
            # import time, and this line runs once per human approval. Hoisting
            # it would put all of that behind every `import hitl_manager`.
            from app.agents.runtime import AgentExecutor
            executor = AgentExecutor(ComplianceEngine(), self)
            result = await executor.execute_skill(
                skill_def, context, hitl_pre_approved=True
            )

            # A resume blocked at a pre-execution gate (compliance/fairness/
            # audit) never reaches the engine's persist step - finalize the
            # row here so an approved-then-blocked execution cannot sit in
            # RUNNING forever looking alive.
            terminal = result.get("status", ExecutionStatus.FAILED)
            if terminal not in (ExecutionStatus.SUCCESS_CLEAN,):
                async with AsyncSessionLocal() as session:
                    await session.execute(
                        update(SkillExecution)
                        .where(SkillExecution.id == execution_id,
                               # "FAILED" included so a retried FAILED_RESUME
                               # that then blocks at a gate still finalizes.
                               SkillExecution.agent_state.in_(
                                   [AgentState.RUNNING, AgentState.PAUSED,
                                    AgentState.FAILED, None]))
                        .values(agent_state=AgentState.FAILED, status=terminal,
                                outcome_type=terminal,
                                completed_at=datetime.now(timezone.utc))
                    )
                    await session.commit()

            # 4. Emit activity event for the resumed execution
            feed = ActivityFeedService()
            await feed.emit(
                event_type=ActivityEventType.AGENT_COMPLETED,
                title=f"Resumed: {skill_id_name}",
                description=f"Execution completed after human approval. Steps run: {len(result.get('reasoning_chain', []))}",
                tenant_id=tenant_id,
                severity=ActivitySeverity.INFO,
                source_type="execution",
                source_id=execution_id,
            )
            logger.info(f"[HITL] Execution {execution_id} resumed and completed successfully")
            return True

        except Exception as e:
            logger.error(f"[HITL] Error resuming execution {execution_id}: {e}", exc_info=True)
            async with AsyncSessionLocal() as session:
                await session.execute(
                    update(SkillExecution)
                    .where(SkillExecution.id == execution_id)
                    .values(agent_state=AgentState.FAILED,
                            status=ExecutionStatus.FAILED_RESUME)
                )
                await session.commit()
            return False


# Global singleton
hitl_manager = HITLManager()
