import logging

import redis.asyncio as redis
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from app.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

redis_client = None

async def init_redis():
    """Connect to Redis if reachable; otherwise run without it (in-memory fallbacks)."""
    global redis_client
    try:
        client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        await client.ping()
        redis_client = client
        logger.info(f"[Redis] Connected: {settings.REDIS_URL}")
    except Exception as e:
        redis_client = None
        logger.warning(f"[Redis] Unreachable ({e}) — falling back to in-memory queues")

async def get_redis():
    """Return the shared Redis client, or None when Redis is not available."""
    return redis_client

async def close_redis():
    global redis_client
    if redis_client:
        await redis_client.close()
        redis_client = None

class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_requests: int = 100, window_seconds: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds

    async def dispatch(self, request: Request, call_next):
        if not redis_client:
            return await call_next(request)

        # Skip rate limiting for dev if desired, but we'll apply it globally for safety
        client_ip = request.client.host if request.client else "unknown"
        key = f"rate_limit:{client_ip}"
        
        try:
            current = await redis_client.get(key)
            if current and int(current) >= self.max_requests:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too Many Requests"}
                )
            
            pipe = redis_client.pipeline()
            pipe.incr(key)
            pipe.expire(key, self.window_seconds)
            await pipe.execute()
        except Exception:
            # Fallback if Redis is down
            pass

        response = await call_next(request)
        return response
