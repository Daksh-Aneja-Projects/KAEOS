import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from datetime import datetime, timezone
import json

# The broadcast bus itself lives in the service layer (app.services.realtime);
# these routes are one of its consumers. Re-exported here because app/main.py
# still starts the subscriber via `from app.api.routes.ws import manager`.
from app.services.realtime import manager

__all__ = ["router", "manager", "websocket_endpoint"]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ws", tags=["WebSockets"])


def _extract_ws_token(sec_protocol_header: str, query_token: str | None):
    """Pull the bearer token from the Sec-WebSocket-Protocol header if the client
    offered ``["kaeos-bearer", <token>]`` (keeps it out of the query string / logs);
    otherwise fall back to the ``?token=`` query param. Returns (token, subprotocol)."""
    offered = [p.strip() for p in (sec_protocol_header or "").split(",") if p.strip()]
    if len(offered) >= 2 and offered[0] == "kaeos-bearer":
        return offered[1], "kaeos-bearer"
    return query_token, None


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
