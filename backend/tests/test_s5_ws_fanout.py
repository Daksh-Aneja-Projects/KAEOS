"""S5.6.8 — local WebSocket fan-out must be concurrent, not serial.

The delivery loop in ``ConnectionManager._deliver_local_tenant`` runs inside the
single per-worker Redis subscriber task. When it awaited each socket in turn, N
stalled-but-connected clients cost N x the send timeout SEQUENTIALLY, so ten
stalled browser tabs head-of-line-blocked every other socket on the worker for
~50s per message. These tests pin the sends down as concurrent.
"""

import asyncio
import time

import pytest

from app.api.routes import ws as ws_mod
from app.api.routes.ws import ConnectionManager

# Shrink the per-send budget so the wall-clock test is fast but still
# discriminating: 2 stalled sockets cost ~0.5s concurrently and >=1.0s serially,
# so a bound of 0.9s passes only on the concurrent implementation.
_T = 0.5
_BOUND = 0.9


@pytest.fixture(autouse=True)
def _fast_timeout(monkeypatch):
    monkeypatch.setattr(ws_mod, "_SEND_TIMEOUT_S", _T)


class _Healthy:
    def __init__(self):
        self.received = []

    async def send_json(self, msg):
        self.received.append(msg)


class _Stalled:
    """Connected, accepts the send, never completes it (TCP backpressure)."""

    async def send_json(self, msg):
        await asyncio.sleep(30)


class _Broken:
    """Socket already gone: the send raises straight away."""

    async def send_json(self, msg):
        raise RuntimeError("socket closed")


async def test_all_healthy_receive_and_stay_tracked():
    mgr = ConnectionManager()
    conns = [_Healthy(), _Healthy(), _Healthy()]
    mgr.active_connections["t1"] = list(conns)

    n = await mgr._deliver_local_tenant("t1", {"type": "gate_event"})

    assert n == 3
    assert all(c.received == [{"type": "gate_event"}] for c in conns)
    assert mgr.active_connections["t1"] == conns


async def test_stalled_sockets_do_not_serialize_the_fanout():
    mgr = ConnectionManager()
    good_a, good_b = _Healthy(), _Healthy()
    bad_a, bad_b = _Stalled(), _Stalled()
    mgr.active_connections["t1"] = [bad_a, good_a, bad_b, good_b]

    started = time.perf_counter()
    n = await mgr._deliver_local_tenant("t1", {"type": "hitl_required"})
    elapsed = time.perf_counter() - started

    # The load-bearing assertion: serial delivery cannot finish under 2 x _T.
    assert elapsed < _BOUND, f"fan-out took {elapsed:.2f}s, sends are still serial"
    assert n == 2
    assert good_a.received and good_b.received
    assert mgr.active_connections["t1"] == [good_a, good_b]


async def test_raising_socket_is_dropped_without_affecting_peers():
    mgr = ConnectionManager()
    good = _Healthy()
    mgr.active_connections["t1"] = [_Broken(), good]

    n = await mgr._deliver_local_tenant("t1", {"type": "activity_feed"})

    assert n == 1
    assert good.received == [{"type": "activity_feed"}]
    assert mgr.active_connections["t1"] == [good]


async def test_disconnect_during_send_does_not_crash_cleanup():
    """A socket removed concurrently is still queued for removal; ``.remove()``
    on a missing item raises ValueError, so cleanup must guard membership."""
    mgr = ConnectionManager()
    good = _Healthy()

    class _Vanishing:
        async def send_json(self, msg):
            mgr.active_connections["t1"].remove(self)
            raise RuntimeError("client went away mid-send")

    vanishing = _Vanishing()
    mgr.active_connections["t1"] = [vanishing, good]

    n = await mgr._deliver_local_tenant("t1", {"type": "agent_status"})

    assert n == 1
    assert mgr.active_connections["t1"] == [good]

    # Harsher variant: the whole tenant entry disappears mid-send.
    class _VanishingTenant:
        async def send_json(self, msg):
            mgr.active_connections.pop("t2", None)
            raise RuntimeError("last socket for the tenant went away")

    mgr.active_connections["t2"] = [_VanishingTenant()]
    assert await mgr._deliver_local_tenant("t2", {"type": "agent_status"}) == 0
    assert "t2" not in mgr.active_connections


async def test_empty_tenant_entry_is_reaped():
    mgr = ConnectionManager()
    mgr.active_connections["t1"] = []

    assert await mgr._deliver_local_tenant("t1", {"type": "system_health"}) == 0
    assert "t1" not in mgr.active_connections
