"""
Phase 2B regression — HITL approver non-repudiation.

The HR HITL approve/reject endpoints previously recorded a client-supplied
``body.approver`` (default "human"), so the audit said who the *client claimed*,
not who authenticated. These tests prove the recorded approver is now derived
from the authenticated principal and a spoofed body value is ignored.
"""
import pytest

from app.core.tenant import approver_identity

pytestmark = pytest.mark.asyncio


def test_approver_identity_prefers_authenticated_fields():
    assert approver_identity({"email": "a@b.com", "name": "X"}) == "a@b.com"
    assert approver_identity({"user_id": "u1", "name": "X"}) == "u1"
    assert approver_identity({"name": "X"}) == "X"
    assert approver_identity({"tenant_id": "t1", "role": "operator"}) == "t1:operator"


async def test_hr_hitl_ignores_client_supplied_approver(monkeypatch):
    from app.hr.api.v1 import router as hr_router
    from app.hr.api.v1.router import HITLDecision, hitl_approve, hitl_reject

    captured = {}

    class FakeManager:
        async def resolve_hitl(self, execution_id, approved, approver, reason, tenant_id=None):
            captured["approver"] = approver
            captured["approved"] = approved
            return True

    import app.services.hitl_manager as hm
    monkeypatch.setattr(hm, "hitl_manager", FakeManager())

    async def _noop(**kwargs):
        return None
    monkeypatch.setattr(hr_router, "record_security_event", _noop)

    tenant = {"tenant_id": "t1", "email": "real@corp.com", "role": "operator", "name": "Real"}

    body = HITLDecision(approver="attacker@evil.com", reason="approve it")
    res = await hitl_approve("exec1", body, tenant)
    assert captured["approver"] == "real@corp.com"
    assert captured["approved"] is True
    assert res["approver"] == "real@corp.com"
    assert "attacker" not in captured["approver"]

    res2 = await hitl_reject("exec2", HITLDecision(approver="attacker@evil.com"), tenant)
    assert captured["approver"] == "real@corp.com"
    assert captured["approved"] is False
    assert res2["approver"] == "real@corp.com"
