"""
Ambient request context.

The LLM router sits far below the request handlers, so it never knew which
tenant or skill a model call belonged to - which is why cost metering was
never wired and /billing ended up reporting seeded rows. These contextvars
carry that identity down without threading it through every signature.

contextvars are asyncio-task-local: concurrent requests cannot see each
other's values.
"""
from contextvars import ContextVar

current_tenant_id: ContextVar[str | None] = ContextVar("current_tenant_id", default=None)
current_skill_id: ContextVar[str | None] = ContextVar("current_skill_id", default=None)
current_execution_id: ContextVar[str | None] = ContextVar("current_execution_id", default=None)
# Per-request correlation id (X-Request-ID). Set by RequestIdMiddleware and read
# by the logging CorrelationIdFilter so every log line a request produces - at
# any depth, across any module - carries the same id, making one request's whole
# footprint greppable in aggregated logs.
current_request_id: ContextVar[str | None] = ContextVar("current_request_id", default=None)
# Who triggered the work in flight, when a person did. Background jobs (the
# scheduler, precog, the autonomy governor) leave this None, which is how a
# live UI can tell "my action" from "something the system started on its own".
current_actor: ContextVar[str | None] = ContextVar("current_actor", default=None)
# The request-scoped AsyncSession, published by get_db so the gate pipeline can
# release its pooled connection before minutes of LLM calls (see
# AgentExecutor.execute_skill). None outside a request; typed loosely to keep
# this module import-light (no sqlalchemy import at context load).
current_request_db: ContextVar = ContextVar("current_request_db", default=None)
