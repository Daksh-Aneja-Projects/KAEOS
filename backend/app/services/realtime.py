"""Real-time broadcast bus (S6 M8.1).

The connection registry and the cross-worker Redis fan-out are a SERVICE: core,
agents and other services publish onto it, and the WebSocket routes in
``app.api.routes.ws`` are just one consumer. It used to live in the route module,
so every publisher imported upward into the presentation layer. Nothing here may
import from ``app.api``.
"""

import asyncio
import logging
from typing import Dict, List, Any
from fastapi import WebSocket
from datetime import datetime, timezone
import json

logger = logging.getLogger(__name__)

# Redis channel every worker publishes gate/HITL/activity events to and every
# worker subscribes back on. This is what makes a gate event emitted on worker A
# reach a browser whose socket lives on worker B.
_WS_CHANNEL = "kaeos:ws:broadcast"

# Per-socket send budget for local fan-out. Module-level so tests can shrink it.
_SEND_TIMEOUT_S = 5.0


class ConnectionManager:
    """Multi-tenant WebSocket connection manager with broadcast support."""

    def __init__(self):
        # Maps tenant_id -> list of active WebSockets
        self.active_connections: Dict[str, List[WebSocket]] = {}
        # Per-worker Redis subscriber task (set by run_subscriber via main.py).
        self._subscriber_task: "asyncio.Task | None" = None

    MAX_CONNECTIONS_PER_TENANT = 50

    async def connect(self, websocket: WebSocket, tenant_id: str, subprotocol: str | None = None):
        if tenant_id not in self.active_connections:
            self.active_connections[tenant_id] = []
        if len(self.active_connections[tenant_id]) >= self.MAX_CONNECTIONS_PER_TENANT:
            await websocket.close(code=1008, reason="Too many connections for this tenant")
            logger.warning(f"WebSocket rejected for tenant {tenant_id}: connection limit reached")
            return False
        # Echo the negotiated subprotocol (the browser closes the socket if it
        # offered one and the server does not select it).
        await websocket.accept(subprotocol=subprotocol)
        self.active_connections[tenant_id].append(websocket)
        logger.info(f"WebSocket connected for tenant {tenant_id}. Active: {len(self.active_connections[tenant_id])}")

        # Send connection confirmation
        await websocket.send_json({
            "type": "connected",
            "tenant_id": tenant_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "message": "KAEOS Live Feed connected",
        })

    def disconnect(self, websocket: WebSocket, tenant_id: str):
        if tenant_id in self.active_connections:
            if websocket in self.active_connections[tenant_id]:
                self.active_connections[tenant_id].remove(websocket)
            if not self.active_connections[tenant_id]:
                del self.active_connections[tenant_id]
        logger.info(f"WebSocket disconnected for tenant {tenant_id}")

    async def _publish(self, envelope: Dict[str, Any]) -> bool:
        """Fan an event out to every worker via Redis pub/sub. Returns True when
        it was published (each worker's subscriber then delivers to its own local
        sockets, including this worker's), False when Redis is unavailable so the
        caller falls back to local-only delivery (single-instance dev)."""
        try:
            from app.core.redis import get_redis
            client = await get_redis()
            if client is None:
                return False
            await client.publish(_WS_CHANNEL, json.dumps(envelope, default=str))
            return True
        except Exception as e:
            logger.debug(f"[WS] redis publish failed, local fallback: {e}")
            return False

    async def _deliver_local_tenant(self, tenant_id: str, message: Dict[str, Any]) -> int:
        """Send to THIS worker's sockets for a tenant, concurrently. Returns recipients."""
        conns = list(self.active_connections.get(tenant_id, []))

        async def _send_one(conn):
            try:
                # Bounded send: a client that is connected but stalled (TCP
                # backpressure, no exception) would otherwise block the single
                # subscriber loop and head-of-line-block delivery to everyone
                # else. Time it out and drop it.
                await asyncio.wait_for(conn.send_json(message), timeout=_SEND_TIMEOUT_S)
                return None
            except Exception:
                # Gone away or stalled past the timeout; report for removal and
                # let the rest of the fan-out finish.
                return conn

        # Fan out concurrently: sends overlap, so N stalled clients cost ONE
        # timeout in total rather than N x timeout serially (10 stalled tabs
        # used to stall the subscriber loop, and therefore every other socket
        # on this worker, for 50s per message).
        results = await asyncio.gather(*(_send_one(c) for c in conns))
        dead = [c for c in results if c is not None]
        # Clean dead connections. Mutate the actual tracked list (not a fresh
        # default) and guard membership — under concurrency a connection may
        # already be gone, and .remove() on a missing item raises ValueError.
        tracked = self.active_connections.get(tenant_id)
        if tracked is not None:
            for c in dead:
                if c in tracked:
                    tracked.remove(c)
            if not tracked:
                self.active_connections.pop(tenant_id, None)
        return len(conns) - len(dead)

    async def _deliver_local_all(self, message: Dict[str, Any]) -> int:
        # Tenants fan out concurrently too: a system-wide broadcast used to pay
        # each tenant's worst case in sequence (T x one send timeout), and each
        # per-tenant call only ever mutates its own key, so gathering is safe.
        counts = await asyncio.gather(*(
            self._deliver_local_tenant(t, message)
            for t in list(self.active_connections.keys())
        ))
        return sum(counts)

    async def broadcast_to_tenant(self, tenant_id: str, message: Dict[str, Any]) -> int:
        """Broadcast to all connections for a tenant across ALL workers.

        Published to Redis so a socket on another worker/replica receives it too;
        the local return count is only meaningful on the Redis-absent fallback
        path (callers use it for a debug log, not correctness)."""
        if await self._publish({"scope": "tenant", "tenant_id": tenant_id, "message": message}):
            return 0
        return await self._deliver_local_tenant(tenant_id, message)

    async def broadcast_to_all(self, message: Dict[str, Any]) -> int:
        """Broadcast to ALL tenants across ALL workers (system-level events)."""
        if await self._publish({"scope": "all", "message": message}):
            return 0
        return await self._deliver_local_all(message)

    async def run_subscriber(self) -> None:
        """Per-worker loop: subscribe to the fan-out channel and deliver each
        published event to THIS worker's local sockets. Started once per worker
        in main.py's lifespan; cancelled on shutdown. Re-checks for Redis every
        5s so it self-heals if Redis comes up after boot."""
        while True:
            try:
                from app.core.redis import get_redis
                client = await get_redis()
                if client is None:
                    await asyncio.sleep(5)  # no Redis -> broadcasts stay local
                    continue
                pubsub = client.pubsub()
                await pubsub.subscribe(_WS_CHANNEL)
                logger.info("[WS] subscribed to %s for cross-worker fan-out", _WS_CHANNEL)
                async for msg in pubsub.listen():
                    if msg.get("type") != "message":
                        continue
                    try:
                        env = json.loads(msg["data"])
                        if env.get("scope") == "all":
                            await self._deliver_local_all(env["message"])
                        else:
                            await self._deliver_local_tenant(env["tenant_id"], env["message"])
                    except Exception as e:
                        logger.debug(f"[WS] fan-out delivery error: {e}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"[WS] subscriber loop error, restarting in 5s: {e}")
                await asyncio.sleep(5)

    def tenant_connection_count(self, tenant_id: str) -> int:
        return len(self.active_connections.get(tenant_id, []))


# Global singleton — imported by EventBus and ActivityFeedService
manager = ConnectionManager()
