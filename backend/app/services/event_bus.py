from typing import Dict, List, Any
from datetime import datetime, timezone
from enum import Enum
import asyncio
import hashlib
import json
import uuid
import logging
import httpx

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.events import SystemEvent, WebhookSubscriptionModel

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    # Core KAEOS
    RULE_CREATED = "rule.created"
    RULE_VALIDATED = "rule.validated"
    RULE_DECAYED = "rule.decayed"
    RULE_ARCHIVED = "rule.archived"
    SKILL_COMPILED = "skill.compiled"
    SKILL_EXECUTED = "skill.executed"
    SKILL_FAILED = "skill.failed"
    HITL_REQUESTED = "hitl.requested"
    HITL_APPROVED = "hitl.approved"
    HITL_REJECTED = "hitl.rejected"
    COMPLIANCE_VIOLATION = "compliance.violation"
    DECAY_ALERT = "decay.alert"
    AGENT_ANOMALY = "agent.anomaly"
    ELICITATION_GENERATED = "elicitation.generated"
    REGULATORY_PATCH = "regulatory.patch"
    FEDERATED_EXPORT = "federated.export"
    SYSTEM_HEALTH = "system.health"
    
    # Workforce Layer (New)
    DEPARTMENT_DEPLOYED = "department.deployed"
    DEPARTMENT_PAUSED = "department.paused"
    CAPABILITY_ACTIVATED = "capability.activated"
    PROCESS_STARTED = "process.started"
    PROCESS_COMPLETED = "process.completed"
    PROCESS_FAILED = "process.failed"
    AGENT_DECISION_MADE = "agent.decision_made"
    
    # HR Specific (New)
    HR_CASE_OPENED = "hr.case.opened"
    HR_CASE_RESOLVED = "hr.case.resolved"
    CANDIDATE_SCREENED = "hr.candidate.screened"
    OFFER_SENT = "hr.offer.sent"
    EMPLOYEE_ONBOARDED = "hr.employee.onboarded"
    EMPLOYEE_OFFBOARDED = "hr.employee.offboarded"
    LEAVE_REQUESTED = "hr.leave.requested"
    REVIEW_COMPLETED = "hr.review.completed"


class EventBus:
    """Production event bus — writes to DB and dispatches to webhook subscribers."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.webhook_queue = asyncio.Queue(maxsize=1000)
            cls._instance.worker_task = None
        return cls._instance

    async def subscribe(self, db: AsyncSession, endpoint: str, events: List[EventType],
                  secret: str = None, tenant_id: str = None, name: str = "default") -> WebhookSubscriptionModel:
        """Create a new webhook subscription stored in the database.
        tenant_id is required (kept keyword-only-with-guard because it follows an
        optional param); a missing tenant fails loudly rather than writing a
        NULL/"default" subscription that would leak events across tenants."""
        if not tenant_id:
            raise ValueError("EventBus.subscribe requires a tenant_id")
        sub = WebhookSubscriptionModel(
            tenant_id=tenant_id,
            name=name,
            endpoint=endpoint,
            events=[e.value for e in events],
            secret=secret or hashlib.sha256(uuid.uuid4().hex.encode()).hexdigest()[:32]
        )
        db.add(sub)
        await db.commit()
        await db.refresh(sub)
        logger.info(f"[EventBus] New DB subscription: {name} → {endpoint} for {len(events)} events")
        return sub

    async def unsubscribe(self, db: AsyncSession, sub_id: str, tenant_id: str | None = None) -> bool:
        """Deactivate a subscription. Request paths MUST pass tenant_id: keyed
        on sub_id alone, any tenant could silence another's event delivery."""
        conds = [WebhookSubscriptionModel.id == sub_id]
        if tenant_id is not None:
            conds.append(WebhookSubscriptionModel.tenant_id == tenant_id)
        q = await db.execute(select(WebhookSubscriptionModel).where(*conds))
        sub = q.scalar_one_or_none()
        if sub:
            sub.active = False
            db.add(sub)
            await db.commit()
            return True
        return False

    async def emit(self, event_type: EventType, payload: Dict[str, Any],
                   tenant_id: str):
        """Emit an event, persist it to the DB, and notify subscribers.
        tenant_id is REQUIRED - no default, so an event is never persisted
        against a bogus "default" tenant."""
        from app.core.database import AsyncSessionLocal
        
        # We process emission in a new DB session since it may be called from async contexts
        # where the parent transaction is closing or we don't want to block
        
        event_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc)
        
        async with AsyncSessionLocal() as db:
            # 1. Persist Event
            sys_event = SystemEvent(
                id=event_id,
                tenant_id=tenant_id,
                event_type=event_type.value,
                payload=payload,
                timestamp=timestamp
            )
            db.add(sys_event)
            
            # 2. Find Subscribers
            # In production with many tenants, we only query active subs for this tenant
            q = await db.execute(
                select(WebhookSubscriptionModel)
                .where(WebhookSubscriptionModel.active == True)
                .where(WebhookSubscriptionModel.tenant_id == tenant_id)
            )
            subs = q.scalars().all()
            
            # Filter subs that care about this event
            matching_subs = [s for s in subs if event_type.value in s.events]
            
            # Save DB
            await db.commit()
            
            # 3. Publish to Redis for background processing
            if matching_subs:
                event_data = {
                    "id": event_id,
                    "type": event_type.value,
                    "tenant_id": tenant_id,
                    "payload": payload,
                    "timestamp": timestamp.isoformat()
                }
                try:
                    from app.core.redis import get_redis
                    redis = await get_redis()
                    if redis:
                        # Serialize subscribers to dicts for sending over pub/sub
                        subs_dicts = [{"id": s.id, "endpoint": s.endpoint, "secret": s.secret} for s in matching_subs]
                        message = json.dumps({"event_data": event_data, "subs": subs_dicts})
                        await redis.publish("kaeos_events", message)
                    else:
                        logger.warning("[EventBus] Redis not available, using in-memory queue as fallback")
                        self.webhook_queue.put_nowait((event_data, matching_subs))
                except Exception as e:
                    logger.error(f"[EventBus] Error publishing event to Redis: {e}")
                    try:
                        self.webhook_queue.put_nowait((event_data, matching_subs))
                    except asyncio.QueueFull:
                        pass

            # 4. Broadcast to all connected WebSocket clients for this tenant (real-time push)
            try:
                from app.api.routes.ws import manager as ws_manager
                ws_payload = {
                    "type": "event",
                    "event_type": event_type.value,
                    "payload": payload,
                    "timestamp": timestamp.isoformat(),
                    "event_id": event_id,
                }
                await ws_manager.broadcast_to_tenant(tenant_id, ws_payload)
            except Exception as ws_err:
                # Non-fatal: WS broadcast failure never blocks event emission
                logger.debug(f"[EventBus] WS broadcast skipped: {ws_err}")

        return {"id": event_id, "status": "persisted", "subscribers_notified": len(matching_subs)}

    async def _worker_loop(self):
        """Background worker that dispatches webhooks.

        With Redis: listens on the kaeos_events pub/sub channel.
        Without Redis: drains the in-memory fallback queue that emit() fills.
        """
        logger.info("[EventBus] Starting webhook worker loop...")

        while True:
            try:
                from app.core.redis import get_redis
                redis = await get_redis()
                if not redis:
                    # No Redis — consume the in-memory fallback queue directly
                    try:
                        event_data, subs = await asyncio.wait_for(self.webhook_queue.get(), timeout=5)
                        await self._dispatch_webhooks(event_data, subs)
                    except asyncio.TimeoutError:
                        pass
                    continue


                pubsub = redis.pubsub()
                await pubsub.subscribe("kaeos_events")
                
                async for message in pubsub.listen():
                    if message["type"] == "message":
                        try:
                            data = json.loads(message["data"])
                            event_data = data.get("event_data")
                            subs = data.get("subs")
                            if event_data and subs:
                                await self._dispatch_webhooks(event_data, subs)
                        except Exception as e:
                            logger.error(f"[EventBus] Error processing redis message: {e}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[EventBus] Webhook worker crashed: {e}, restarting in 5s...")
                await asyncio.sleep(5)

    async def _dispatch_webhooks(self, event_data: Dict, subs: List[Any]):
        """Background task to POST webhooks."""
        from app.core.database import AsyncSessionLocal
        
        async with httpx.AsyncClient() as client:
            async with AsyncSessionLocal() as db:
                for sub in subs:
                    # Handle both SQLAlchemy models and dictionary payloads from Redis
                    is_dict = isinstance(sub, dict)
                    sub_id = sub.get("id") if is_dict else sub.id
                    sub_secret = sub.get("secret") if is_dict else sub.secret
                    sub_endpoint = sub.get("endpoint") if is_dict else sub.endpoint

                    try:
                        signature = hashlib.sha256(
                            f"{sub_secret}|{json.dumps(event_data, sort_keys=True, default=str)}".encode()
                        ).hexdigest()

                        res = await client.post(
                            sub_endpoint,
                            json=event_data,
                            headers={"X-KAEOS-Signature": signature},
                            timeout=5.0
                        )
                        res.raise_for_status()

                        logger.info(f"[EventBus] Delivered {event_data['type']} → {sub_endpoint}")
                        # Re-fetch sub to update metrics safely
                        q = await db.execute(select(WebhookSubscriptionModel).where(WebhookSubscriptionModel.id == sub_id))
                        db_sub = q.scalar_one_or_none()
                        if db_sub:
                            db_sub.delivery_count += 1
                            db_sub.last_delivered_at = datetime.now(timezone.utc)
                            db.add(db_sub)
                    except Exception as e:
                        logger.warning(f"[EventBus] Delivery failed to {sub_endpoint}: {e}")
                        q = await db.execute(select(WebhookSubscriptionModel).where(WebhookSubscriptionModel.id == sub_id))
                        db_sub = q.scalar_one_or_none()
                        if db_sub:
                            db_sub.failure_count += 1
                            db.add(db_sub)
                
                await db.commit()

# Singleton
event_bus = EventBus()
