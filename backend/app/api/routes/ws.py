import logging
from typing import Dict, List, Any
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from datetime import datetime, timezone
import json

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ws", tags=["WebSockets"])


class ConnectionManager:
    """Multi-tenant WebSocket connection manager with broadcast support."""

    def __init__(self):
        # Maps tenant_id -> list of active WebSockets
        self.active_connections: Dict[str, List[WebSocket]] = {}

    MAX_CONNECTIONS_PER_TENANT = 50

    async def connect(self, websocket: WebSocket, tenant_id: str):
        if tenant_id not in self.active_connections:
            self.active_connections[tenant_id] = []
        if len(self.active_connections[tenant_id]) >= self.MAX_CONNECTIONS_PER_TENANT:
            await websocket.close(code=1008, reason="Too many connections for this tenant")
            logger.warning(f"WebSocket rejected for tenant {tenant_id}: connection limit reached")
            return False
        await websocket.accept()
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

    async def broadcast_to_tenant(self, tenant_id: str, message: Dict[str, Any]) -> int:
        """Broadcast to all connections for a tenant. Returns number of recipients."""
        sent = 0
        dead = []
        for conn in self.active_connections.get(tenant_id, []):
            try:
                await conn.send_json(message)
                sent += 1
            except Exception:
                dead.append(conn)
        # Clean dead connections
        for c in dead:
            self.active_connections.get(tenant_id, []).remove(c)
        return sent

    async def broadcast_to_all(self, message: Dict[str, Any]) -> int:
        """Broadcast to ALL tenants (system-level events)."""
        total = 0
        for tenant_id in list(self.active_connections.keys()):
            total += await self.broadcast_to_tenant(tenant_id, message)
        return total

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

    Auth: outside DEV_MODE the `token` query param must be a valid JWT or
    kt_ API key whose tenant matches the path tenant — WebSockets bypass
    TenantMiddleware, so the check lives here.
    """
    from app.core.config import get_settings
    settings = get_settings()
    if not settings.DEV_MODE:
        authorized = False
        if token:
            if token.startswith("kt_"):
                from app.core.auth import _API_KEYS, hash_key
                key_meta = _API_KEYS.get(hash_key(token))
                authorized = bool(
                    key_meta
                    and key_meta.get("active", True)
                    and key_meta.get("tenant_id") == tenant_id
                )
            else:
                from app.services.auth import decode_token
                payload = decode_token(token)
                authorized = bool(payload and payload.get("tenant_id") == tenant_id)
        if not authorized:
            logger.warning(f"[WS] Rejected unauthenticated connection for tenant {tenant_id}")
            await websocket.close(code=1008, reason="Unauthorized")
            return

    connected = await manager.connect(websocket, tenant_id)
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
