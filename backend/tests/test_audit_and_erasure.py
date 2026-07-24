"""
Phase 2D + 2E-erasure regression.

2D: the post-execution audit gate requires the actual audited datum (a financial
    amount for SOX, a lawful basis for GDPR/HIPAA/CCPA), not just a "logged" flag.
2E: GDPR erasure purges the subject's embeddings from the vector store.
"""
import pytest

from app.services.compliance import ComplianceEngine

pytestmark = pytest.mark.asyncio


def test_audit_gate_requires_real_amount_for_sox():
    eng = ComplianceEngine()
    # Flag set but no amount -> not satisfied.
    assert eng.enforce_audit_requirements(["SOX"], {"financial_amount_logged": True}) is False
    # Flag set with a real amount -> satisfied.
    assert eng.enforce_audit_requirements(["SOX"], {"financial_amount_logged": True, "amount": 4200.0}) is True
    # No flag -> not satisfied.
    assert eng.enforce_audit_requirements(["SOX"], {"amount": 4200.0}) is False


def test_audit_gate_requires_legal_basis_for_gdpr_family():
    eng = ComplianceEngine()
    for tag in ("GDPR", "HIPAA", "CCPA"):
        assert eng.enforce_audit_requirements([tag], {"data_processing_basis_logged": True}) is False
        assert eng.enforce_audit_requirements(
            [tag], {"data_processing_basis_logged": True, "legal_basis": "consent"}
        ) is True


def test_audit_gate_passes_when_no_regulated_tags():
    eng = ComplianceEngine()
    assert eng.enforce_audit_requirements([], {}) is True
    assert eng.enforce_audit_requirements(["INTERNAL"], {}) is True


async def test_erasure_purges_subject_embeddings():
    from app.core.polystore.vector_store import get_vector_store

    store = get_vector_store()
    tenant = "tenant_erase"
    # One embedding referencing the subject (id in metadata), one unrelated.
    await store.upsert("v-subj", tenant, "performance note for emp_erase_1",
                       [0.1, 0.2, 0.3], metadata={"employee_id": "emp_erase_1"})
    await store.upsert("v-other", tenant, "unrelated org note",
                       [0.4, 0.5, 0.6], metadata={"employee_id": "emp_keep_9"})

    deleted = await store.delete_subject(tenant, subject_ids=["emp_erase_1"], subject_texts=[])
    assert deleted == 1

    # The unrelated embedding must survive.
    remaining = await store.delete_subject(tenant, subject_ids=["emp_keep_9"])
    assert remaining == 1
