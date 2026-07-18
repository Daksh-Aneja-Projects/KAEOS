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
        if request.url.path in self.SKIP_PATHS:
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
            f"[{request.method}] {request.url.path} → {response.status_code} "
            f"({duration_ms}ms) tenant={tenant_id} req={request_id}"
        )

        response.headers["X-Response-Time"] = f"{duration_ms}ms"
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Simple in-memory rate limiter per tenant.
    Default: 200 requests/minute per tenant. Override via tenant metadata.

    NOTE: For production multi-instance deployments, replace with Redis-based
    rate limiting (e.g., fastapi-limiter with Redis backend).
    """

    def __init__(self, app, requests_per_minute: int = 200):
        super().__init__(app)
        self.rpm = requests_per_minute
        self._windows: dict[str, list[float]] = defaultdict(list)

    # Paths exempt from rate limiting
    EXEMPT_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in self.EXEMPT_PATHS:
            return await call_next(request)

        # Identify caller by tenant or IP
        tenant = getattr(request.state, "tenant", None)
        if tenant and isinstance(tenant, dict):
            caller_id = tenant.get("tenant_id", "anonymous")
        else:
            caller_id = request.client.host if request.client else "unknown"

        now = time.time()
        window = self._windows[caller_id]

        # Purge entries older than 60 seconds
        window[:] = [t for t in window if now - t < 60]

        if len(window) >= self.rpm:
            retry_after = int(60 - (now - window[0])) + 1
            logger.warning(f"[RateLimit] {caller_id} exceeded {self.rpm} rpm")
            return JSONResponse(
                status_code=429,
                content={
                    "detail": f"Rate limit exceeded. Max {self.rpm} requests/minute.",
                    "retry_after_seconds": retry_after,
                },
                headers={"Retry-After": str(retry_after)},
            )

        window.append(now)
        return await call_next(request)
