import logging
import json
from typing import Dict, Any
from datetime import datetime, timezone
from app.models.agent_factory import ActivityEventType, ActivitySeverity
from app.core.database import AsyncSessionLocal
from app.models.domain import SkillExecution

logger = logging.getLogger(__name__)

# Redis key prefix for HITL pending approvals (survives restarts)
_HITL_KEY_PREFIX = "kaeos:hitl:"
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

    def _redis_key(self, exec_id: str) -> str:
        return f"{_HITL_KEY_PREFIX}{exec_id}"

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
            from app.core.redis import redis_client
            return redis_client
        except Exception:
            # Redis is optional; without it HITL falls back to DB-only state.
            return None

    async def request_human_confirmation(self, skill: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """Non-blocking: Store pending approval and return immediately with execution_id."""
        exec_id = context.get("execution_id")
        if not exec_id:
            logger.error("No execution ID provided for HITL")
            return {"approved": None, "pending": True, "execution_id": None, "reason": "System error: No execution_id"}

        logger.info(f"[HITL] Approval required for execution {exec_id} — returning immediately (non-blocking)")

        # Emit an event to the activity feed
        from app.services.activity_feed import ActivityFeedService
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

        if redis:
            await redis.setex(self._redis_key(exec_id), _HITL_TTL, json.dumps(pending_data))
        else:
            logger.warning("[HITL] Redis unavailable — using in-memory HITL store (single-instance only)")
            self._memory[exec_id] = pending_data

        # The DATABASE is the source of truth for pending approvals: every
        # Gate-3 pause gets a PENDING_HITL SkillExecution row, so the single
        # /skills/hitl queue lists all approvals and they survive restarts.
        # The Redis/memory record above is a cache carrying the resume payload.
        try:
            async with AsyncSessionLocal() as session:
                from sqlalchemy import select as _select
                existing = (await session.execute(
                    _select(SkillExecution).where(SkillExecution.id == exec_id)
                )).scalar_one_or_none()
                if existing:
                    existing.agent_state = "PAUSED"
                    existing.hitl_required = True
                    if not existing.status:
                        existing.status = "PENDING_HITL"
                else:
                    session.add(SkillExecution(
                        id=exec_id,
                        skill_db_id=skill.get("skill_db_id"),
                        skill_id_name=skill.get("skill_id", "unknown"),
                        tenant_id=tenant_id,
                        status="PENDING_HITL",
                        route_type="GATED_AGENT",
                        agent_state="PAUSED",
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
        from app.services.notifier import notify_fire_and_forget
        # One-click decide links so an approver living in email/Slack never has
        # to log in to unblock autonomy (signed, single-purpose, 7-day TTL).
        try:
            from app.core.config import get_settings
            from app.api.routes.approvals import approval_links
            base = get_settings().PUBLIC_BASE_URL or "http://localhost:8001"
            links = approval_links(exec_id, tenant_id, base)
            link_lines = (f"\nApprove: {links['approve']}\n"
                          f"Reject:  {links['reject']}\n")
        except Exception:
            logger.warning("HITL approval-link build failed for exec %s", exec_id, exc_info=True)
            links, link_lines = {}, ""
        notify_fire_and_forget(
            tenant_id, "hitl.pending",
            subject=f"KAEOS approval needed: {skill.get('skill_id', 'unknown')}",
            body=(f"A governed execution paused for human approval.\n"
                  f"Skill: {skill.get('skill_id', 'unknown')}\n"
                  f"Department: {skill.get('department', 'general')}\n"
                  f"Execution: {exec_id}\n"
                  f"{link_lines}"
                  f"Or review it in KAEOS under My Work."),
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
            await redis.setex(self._redis_key(execution_id), ttl, json.dumps(data))
        else:
            self._memory[execution_id] = data

    async def get_record_department(self, execution_id: str) -> str | None:
        """The department of a pending approval's skill (for scope checks)."""
        record = await self._get_record(execution_id)
        if not record:
            return None
        return (record.get("skill_def") or {}).get("department")

    async def list_pending(self, tenant_id: str) -> list:
        """All PENDING approvals for a tenant, from Redis or the memory store."""
        pending = []
        redis = await self._get_redis()
        if redis:
            try:
                keys = await redis.keys(f"{_HITL_KEY_PREFIX}*")
                for key in keys:
                    raw = await redis.get(key)
                    if raw:
                        data = json.loads(raw)
                        if data.get("tenant_id") == tenant_id and data.get("status") == "PENDING":
                            pending.append(data)
            except Exception as e:
                logger.warning(f"[HITL] Redis scan failed: {e}")
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
                    from sqlalchemy import select as _select
                    owner_q = await session.execute(
                        _select(SkillExecution.tenant_id).where(
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
            from sqlalchemy import select, update
            exec_q = await session.execute(
                select(SkillExecution).where(SkillExecution.id == execution_id)
            )
            execution = exec_q.scalar_one_or_none()
            if execution:
                if execution.agent_state not in ("PENDING_HITL", "PAUSED", None):
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
                    agent_state="RUNNING" if approved else "FAILED",
                    hitl_approved=approved,
                    hitl_approver=approver,
                )
                if not approved:
                    values.update(
                        status="HUMAN_OVERRIDDEN",
                        outcome_type="HUMAN_OVERRIDDEN",
                        completed_at=datetime.now(timezone.utc),
                    )
                result = await session.execute(
                    update(SkillExecution)
                    .where(
                        SkillExecution.id == execution_id,
                        SkillExecution.agent_state.in_(["PENDING_HITL", "PAUSED", None]),
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
                    from app.services import job_queue
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
            import asyncio
            asyncio.create_task(self._resume_from_hitl(execution_id, fallback_record=record))

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
            from sqlalchemy import select
            row = (await session.execute(
                select(SkillExecution).where(SkillExecution.id == execution_id)
            )).scalar_one_or_none()
            if row is not None and (
                row.completed_at is not None
                or (row.agent_state in ("COMPLETED", "FAILED")
                    # FAILED_RESUME means a previous ATTEMPT died, not that the
                    # decision reached a terminal outcome - retry those.
                    and row.status != "FAILED_RESUME")
            ):
                logger.info(f"[HITL] {execution_id} already finalized "
                            f"({row.agent_state}/{row.status}); resume is a no-op")
                return True
        try:
            # 1. Load execution record and the associated compiled Skill from the DB
            async with AsyncSessionLocal() as session:
                from sqlalchemy import select
                from app.models.domain import Skill
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
            context["has_human_approver"] = (
                (execution.hitl_approver if execution else None) or "human-approver"
            )
            if skill_obj is not None:
                context["_skill_obj"] = skill_obj

            from app.agents.runtime import AgentExecutor
            from app.services.compliance import ComplianceEngine
            executor = AgentExecutor(ComplianceEngine(), self)
            result = await executor.execute_skill(
                skill_def, context, hitl_pre_approved=True
            )

            # A resume blocked at a pre-execution gate (compliance/fairness/
            # audit) never reaches the engine's persist step - finalize the
            # row here so an approved-then-blocked execution cannot sit in
            # RUNNING forever looking alive.
            terminal = result.get("status", "FAILED")
            if terminal not in ("SUCCESS_CLEAN",):
                async with AsyncSessionLocal() as session:
                    from sqlalchemy import update
                    await session.execute(
                        update(SkillExecution)
                        .where(SkillExecution.id == execution_id,
                               # "FAILED" included so a retried FAILED_RESUME
                               # that then blocks at a gate still finalizes.
                               SkillExecution.agent_state.in_(
                                   ["RUNNING", "PAUSED", "FAILED", None]))
                        .values(agent_state="FAILED", status=terminal,
                                outcome_type=terminal,
                                completed_at=datetime.now(timezone.utc))
                    )
                    await session.commit()

            # 4. Emit activity event for the resumed execution
            from app.services.activity_feed import ActivityFeedService
            from app.models.agent_factory import ActivityEventType, ActivitySeverity
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
                from sqlalchemy import update
                await session.execute(
                    update(SkillExecution)
                    .where(SkillExecution.id == execution_id)
                    .values(agent_state="FAILED", status="FAILED_RESUME")
                )
                await session.commit()
            return False


# Global singleton
hitl_manager = HITLManager()
