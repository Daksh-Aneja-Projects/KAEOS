"""Observability workstream (theme J) - metrics, correlation ids, WS fan-out.

Unit-lane only: no DB, no Redis, no Ollama. Proves the golden-signal metrics
increment at their real call sites, the correlation-id filter stamps records,
and the WebSocket manager delivers locally when Redis is absent (the
single-instance fallback) without raising.
"""
import logging

from prometheus_client import REGISTRY

from app.core import metrics


def _sample(name, labels):
    return REGISTRY.get_sample_value(name, labels) or 0.0


def test_metrics_defined_and_increment():
    before = _sample("kaeos_gate_transitions_total", {"gate": "compliance", "state": "passed"})
    metrics.GATE_TRANSITIONS.labels(gate="compliance", state="passed").inc()
    after = _sample("kaeos_gate_transitions_total", {"gate": "compliance", "state": "passed"})
    assert after == before + 1


def test_observe_pipeline_records_and_never_raises():
    before = _sample("kaeos_gate_pipeline_total", {"status": "SUCCESS_CLEAN"})
    metrics.observe_pipeline("SUCCESS_CLEAN", 1500)
    after = _sample("kaeos_gate_pipeline_total", {"status": "SUCCESS_CLEAN"})
    assert after == before + 1
    # Bad input must not raise (governance path calls this).
    metrics.observe_pipeline(None, 0)


async def test_emit_gate_increments_counter():
    """The single gate chokepoint feeds the census counter."""
    from app.agents.runtime import AgentExecutor
    ex = AgentExecutor(compliance_engine=None, hitl_manager=None)
    before = _sample("kaeos_gate_transitions_total", {"gate": "fairness", "state": "passed"})
    # No WS connections, Redis absent -> local broadcast is a no-op, never raises.
    await ex._emit_gate({"tenant_id": "t1"}, "fairness", "passed")
    after = _sample("kaeos_gate_transitions_total", {"gate": "fairness", "state": "passed"})
    assert after == before + 1


def test_correlation_id_filter_stamps_request_id():
    from app.core.context import current_request_id
    from app.core.logging import CorrelationIdFilter
    f = CorrelationIdFilter()
    rec = logging.LogRecord("x", logging.INFO, __file__, 1, "hi", None, None)

    # No request in flight -> "-"
    assert f.filter(rec) is True
    assert rec.request_id == "-"

    tok = current_request_id.set("req-abc123")
    try:
        rec2 = logging.LogRecord("x", logging.INFO, __file__, 1, "hi", None, None)
        f.filter(rec2)
        assert rec2.request_id == "req-abc123"
    finally:
        current_request_id.reset(tok)


async def test_ws_local_delivery_when_redis_absent():
    """With Redis unavailable, broadcast falls back to delivering to this
    worker's own sockets (single-instance dev must keep working)."""
    from app.api.routes.ws import ConnectionManager

    class _FakeWS:
        def __init__(self):
            self.received = []

        async def send_json(self, msg):
            self.received.append(msg)

    mgr = ConnectionManager()
    ws = _FakeWS()
    mgr.active_connections["t1"] = [ws]

    # get_redis() returns None in the unit lane -> _publish returns False -> local.
    n = await mgr.broadcast_to_tenant("t1", {"type": "gate_event", "gate": "compliance"})
    assert n == 1
    assert ws.received and ws.received[0]["gate"] == "compliance"


async def test_ws_all_delivery_when_redis_absent():
    from app.api.routes.ws import ConnectionManager

    class _FakeWS:
        def __init__(self):
            self.received = []

        async def send_json(self, msg):
            self.received.append(msg)

    mgr = ConnectionManager()
    a, b = _FakeWS(), _FakeWS()
    mgr.active_connections["t1"] = [a]
    mgr.active_connections["t2"] = [b]
    n = await mgr.broadcast_to_all({"type": "system"})
    assert n == 2
    assert a.received and b.received
