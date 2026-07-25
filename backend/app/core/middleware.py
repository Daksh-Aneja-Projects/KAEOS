"""
KAEOS — Request Middleware Stack
Rate limiting, request ID tracking, and structured request logging.
"""
import time
import uuid
import logging
from collections import defaultdict

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Injects a unique X-Request-ID header into every request/response for tracing."""

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID", f"req-{uuid.uuid4().hex[:12]}")
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Structured request/response logging with latency tracking."""

    # Paths to skip logging (noisy health checks)
    SKIP_PATHS = {"/health", "/docs", "/openapi.json", "/redoc", "/favicon.ico"}

    async def dispatch(self, request: Request, call_next) -> Response:
        # Use the raw ASGI scope path (the router's matched path), never
        # request.url.path — the latter is rebuilt from the attacker-controlled
        # Host header and can be poisoned (GHSA-86qp). Logging the real path keeps
        # the audit trail truthful when a poisoning attempt is made.
        req_path = request.scope["path"]
        if req_path in self.SKIP_PATHS:
            return await call_next(request)

        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 1)

        request_id = getattr(request.state, "request_id", "?")
        tenant = getattr(request.state, "tenant", {})
        tenant_id = tenant.get("tenant_id", "?") if isinstance(tenant, dict) else "?"

        log_level = logging.WARNING if response.status_code >= 400 else logging.INFO
        logger.log(
            log_level,
            f"[{request.method}] {req_path} → {response.status_code} "
            f"({duration_ms}ms) tenant={tenant_id} req={request_id}"
        )

        response.headers["X-Response-Time"] = f"{duration_ms}ms"
        return response


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject over-large request bodies early (OOM guard).

    A single huge upload can exhaust worker memory before any handler runs. This
    rejects by declared Content-Length with 413 — cheap and covers the common
    case. (Chunked/unknown-length bodies bypass this fast check; the ASGI server's
    own limits and the app's typed request models are the backstop there.)
    """

    def __init__(self, app, max_bytes: int):
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next) -> Response:
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > self.max_bytes:
                    return JSONResponse(
                        status_code=413,
                        content={"detail": f"Request body too large (max {self.max_bytes} bytes)."},
                    )
            except ValueError:
                pass  # malformed header — let the server/handler deal with it
        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-tenant rate limiter, backed by Redis when available.

    Under multiple workers/replicas an in-memory window counts each process
    separately, so the effective limit is N times the configured value. When a
    shared Redis is reachable this uses a per-minute fixed-window counter in Redis
    (one shared limit across all workers); it falls back to the in-memory window
    only when Redis is absent (single-instance dev). Default: 200 rpm per tenant.
    """

    def __init__(self, app, requests_per_minute: int = 200):
        super().__init__(app)
        self.rpm = requests_per_minute
        self._windows: dict[str, list[float]] = defaultdict(list)

    # Paths exempt from rate limiting
    EXEMPT_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}

    def _caller_id(self, request: Request) -> str:
        tenant = getattr(request.state, "tenant", None)
        if tenant and isinstance(tenant, dict):
            return tenant.get("tenant_id", "anonymous")
        return request.client.host if request.client else "unknown"

    async def _redis_exceeded(self, caller_id: str, now: float):
        """Shared fixed-window counter. Returns (exceeded, retry_after) or None if
        Redis is unavailable / errored (caller then falls back to in-memory)."""
        try:
            from app.core.redis import get_redis
            client = await get_redis()
            if client is None:
                return None
            bucket = int(now // 60)
            key = f"ratelimit:{caller_id}:{bucket}"
            count = await client.incr(key)
            if count == 1:
                await client.expire(key, 60)
            if count > self.rpm:
                return True, 60 - int(now % 60) + 1
            return False, 0
        except Exception as e:
            logger.warning(f"[RateLimit] Redis check failed ({e}); using in-memory fallback")
            return None

    def _memory_exceeded(self, caller_id: str, now: float):
        window = self._windows[caller_id]
        window[:] = [t for t in window if now - t < 60]
        if len(window) >= self.rpm:
            return True, int(60 - (now - window[0])) + 1
        window.append(now)
        return False, 0

    async def dispatch(self, request: Request, call_next) -> Response:
        # Raw scope path, not request.url.path — a poisoned Host header must not
        # let a caller mimic an exempt path to escape rate limiting (GHSA-86qp).
        if request.scope["path"] in self.EXEMPT_PATHS:
            return await call_next(request)

        caller_id = self._caller_id(request)
        now = time.time()

        result = await self._redis_exceeded(caller_id, now)
        if result is None:
            result = self._memory_exceeded(caller_id, now)
        exceeded, retry_after = result

        if exceeded:
            logger.warning(f"[RateLimit] {caller_id} exceeded {self.rpm} rpm")
            return JSONResponse(
                status_code=429,
                content={
                    "detail": f"Rate limit exceeded. Max {self.rpm} requests/minute.",
                    "retry_after_seconds": retry_after,
                },
                headers={"Retry-After": str(retry_after)},
            )

        return await call_next(request)
