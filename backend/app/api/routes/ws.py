import asyncio
import logging
from typing import Dict, List, Any
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from datetime import datetime, timezone
import json

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ws", tags=["WebSockets"])

# Redis channel every worker publishes gate/HITL/activity events to and every
# worker subscribes back on. This is what makes a gate event emitted on worker A
# reach a browser whose socket lives on worker B.
_WS_CHANNEL = "kaeos:ws:broadcast"


def _extract_ws_token(sec_protocol_header: str, query_token: str | None):
    """Pull the bearer token from the Sec-WebSocket-Protocol header if the client
    offered ``["kaeos-bearer", <token>]`` (keeps it out of the query string / logs);
    otherwise fall back to the ``?token=`` query param. Returns (token, subprotocol)."""
    offered = [p.strip() for p in (sec_protocol_header or "").split(",") if p.strip()]
    if len(offered) >= 2 and offered[0] == "kaeos-bearer":
        return offered[1], "kaeos-bearer"
    return query_token, None


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
        """Send to THIS worker's sockets for a tenant. Returns recipients."""
        sent = 0
        dead = []
        for conn in self.active_connections.get(tenant_id, []):
            try:
                # Bounded send: a client that is connected but stalled (TCP
                # backpressure, no exception) would otherwise block the single
                # subscriber loop and head-of-line-block delivery to everyone
                # else. Time it out and drop it.
                await asyncio.wait_for(conn.send_json(message), timeout=5.0)
                sent += 1
            except Exception:
                # Gone away or stalled past the timeout; queue for removal and
                # keep fanning out to the rest.
                dead.append(conn)
        # Clean dead connections. Mutate the actual tracked list (not a fresh
        # default) and guard membership — under concurrency a connection may
        # already be gone, and .remove() on a missing item raises ValueError.
        conns = self.active_connections.get(tenant_id)
        if conns is not None:
            for c in dead:
                if c in conns:
                    conns.remove(c)
            if not conns:
                self.active_connections.pop(tenant_id, None)
        return sent

    async def _deliver_local_all(self, message: Dict[str, Any]) -> int:
        total = 0
        for tenant_id in list(self.active_connections.keys()):
            total += await self._deliver_local_tenant(tenant_id, message)
        return total

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


@router.websocket("/{tenant_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    tenant_id: str,
    token: str = Query(default=None),
):
    """
    Real-time event stream for a tenant.
    Clients receive: activity_feed, hitl_required, agent_status, system_health.
    Clients send: ping → pong, subscribe → acknowledge.

    Auth: outside DEV_MODE the caller must present a valid JWT or kt_ API key
    whose tenant matches the path tenant — WebSockets bypass TenantMiddleware, so
    the check lives here. The token is taken from the `Sec-WebSocket-Protocol`
    header (offered as `["kaeos-bearer", <token>]`) so it does NOT ride in the
    query string (which lands in proxy/access logs and browser history); the
    `?token=` query param remains a backward-compatible fallback.
    """
    from app.core.config import get_settings
    settings = get_settings()

    token, selected_subprotocol = _extract_ws_token(
        websocket.headers.get("sec-websocket-protocol", ""), token)

    if not settings.DEV_MODE:
        authorized = False
        if token:
            if token.startswith("kt_"):
                from app.core.auth import get_api_key_by_hash, hash_key
                key_meta = await get_api_key_by_hash(hash_key(token))
                authorized = bool(
                    key_meta
                    and key_meta.get("active", True)
                    and key_meta.get("tenant_id") == tenant_id
                )
            else:
                from app.services.auth import decode_token, is_jti_revoked
                payload = decode_token(token)
                authorized = bool(
                    payload
                    and payload.get("tenant_id") == tenant_id
                    and not await is_jti_revoked(payload.get("jti"))
                )
        if not authorized:
            logger.warning(f"[WS] Rejected unauthenticated connection for tenant {tenant_id}")
            await websocket.close(code=1008, reason="Unauthorized")
            return

    connected = await manager.connect(websocket, tenant_id, subprotocol=selected_subprotocol)
    if connected is False:
        return
    try:
        while True:
            raw = await websocket.receive_text()

            # Handle control messages
            try:
                msg = json.loads(raw)
                msg_type = msg.get("type", "")

                if msg_type == "ping":
                    await websocket.send_json({"type": "pong", "timestamp": datetime.now(timezone.utc).isoformat()})

                elif msg_type == "subscribe":
                    # Client subscribes to specific event types
                    channels = msg.get("channels", [])
                    await websocket.send_json({
                        "type": "subscribed",
                        "channels": channels,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })

                else:
                    await websocket.send_json({"type": "error", "message": f"Unknown message type: {msg_type}"})

            except json.JSONDecodeError:
                # Plain text — handle ping as string
                if raw.strip() == "ping":
                    await websocket.send_text("pong")

    except WebSocketDisconnect:
        manager.disconnect(websocket, tenant_id)
    except Exception as e:
        logger.error(f"WebSocket error for tenant {tenant_id}: {e}")
        manager.disconnect(websocket, tenant_id)
