"""H6: memory outcomes are correctable and tenant-scoped.

- update_metadata was keyed on vector_id alone (latent cross-tenant write); it
  now requires and enforces tenant_id.
- store_outcome had zero callers; a reversal now corrects the originating
  decision's memory so recall stops treating a since-reversed write as a clean
  precedent. Decision memories use a deterministic id so no uuid needs threading.
"""
import json

import pytest
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.core.polystore import get_vector_store
from app.services.actuation import Actuator
from app.services.memory.enterprise_memory import EnterpriseMemoryService


async def _read_meta(vid):
    async with AsyncSessionLocal() as s:
        row = (await s.execute(
            text("SELECT metadata FROM polystore_vectors WHERE id = :i"), {"i": vid}
        )).first()
    return json.loads(row[0]) if row and row[0] else None


@pytest.mark.asyncio
async def test_update_metadata_is_tenant_scoped():
    store = get_vector_store()
    await store.upsert(vector_id="vec-X", tenant_id="tA", content="c",
                       embedding=[0.1, 0.2, 0.3], metadata={"outcome": "SUCCESS"},
                       namespace="enterprise_memory")

    # Another tenant must not be able to patch tenant A's vector.
    await store.update_metadata("vec-X", "outcome", "HACKED", tenant_id="tB")
    assert (await _read_meta("vec-X"))["outcome"] == "SUCCESS"

    # The owning tenant can.
    await store.update_metadata("vec-X", "outcome", "REVERSED", tenant_id="tA")
    assert (await _read_meta("vec-X"))["outcome"] == "REVERSED"


@pytest.mark.asyncio
async def test_reversal_marks_the_decision_memory_reversed():
    t = "tenant_h6"
    mid = await EnterpriseMemoryService.store_decision_memory(
        None, t, "ctx", {"execution_id": "exec-h6", "skill_id": "s"},
        outcome="SUCCESS_CLEAN")
    assert mid == f"decision-{t}-exec-h6", "deterministic id keyed on the execution"
    assert (await _read_meta(mid))["outcome"] == "SUCCESS_CLEAN"

    async with AsyncSessionLocal() as s:
        rec = await Actuator.apply_action(
            s, tenant_id=t, system="workday", object_type="employee",
            external_id="E1", operation="CREATE", payload={"x": 1},
            execution_id="exec-h6")
        await Actuator.reverse_action(s, tenant_id=t, action_id=rec.id, actor="op")

    # The reversal fed back into the memory: no longer a clean precedent.
    assert (await _read_meta(mid))["outcome"] == "REVERSED"
