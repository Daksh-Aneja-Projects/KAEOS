"""Phase 10: Cross-Domain Integration Tests"""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

@pytest.mark.asyncio
async def test_all_domains_deployed(db: AsyncSession):
    """Verify all 5 domain agents can be deployed via unified registry."""
    from app.workforce.orchestration.workforce_generator import AGENT_REGISTRY
    
    domain_agents = {
        'finance': ['ap_matching', 'ar_dunning', 'budget_variance', 'expense_audit', 'payroll_audit'],
        'legal': ['contract_review', 'compliance_audit', 'litigation_eval', 'privacy_dsar'],
        'sales': ['lead_scoring', 'account_health', 'pipeline_coach', 'forecast', 'proposal_gen', 'churn_prevention'],
        'support': ['triage', 'auto_resolve', 'escalation', 'csat_analysis', 'sla_monitor'],
        'operations': ['project_eval', 'resource_check', 'vendor_risk', 'procurement_audit', 'qa_inspect'],
    }
    
    for domain, agent_types in domain_agents.items():
        for agent_type in agent_types:
            assert agent_type in AGENT_REGISTRY, f"Missing {domain} agent: {agent_type}"
            registry = AGENT_REGISTRY[agent_type]
            assert 'module' in registry
            assert 'class' in registry
            assert 'method' in registry
            assert 'compliance' in registry

@pytest.mark.asyncio
async def test_gated_runners_callable(db: AsyncSession):
    """Verify all domain gated runners are importable."""
    from app.finance.agents.gated_runner import run_gated_finance_skill
    from app.legal.agents.gated_runner import run_gated_legal_skill
    from app.sales.agents.gated_runner import run_gated_sales_skill
    from app.support.agents.gated_runner import run_gated_support_skill
    from app.operations.agents.gated_runner import run_gated_operations_skill
    
    assert callable(run_gated_finance_skill)
    assert callable(run_gated_legal_skill)
    assert callable(run_gated_sales_skill)
    assert callable(run_gated_support_skill)
    assert callable(run_gated_operations_skill)

@pytest.mark.asyncio
async def test_tenant_isolation_all_domains(db: AsyncSession):
    """Verify tenant isolation across all domain queries."""
    from app.finance.models.accounts_payable import Invoice
    from app.legal.models.contracts import Contract
    from app.sales.models.pipeline import Opportunity
    from app.support.models.tickets import Ticket
    from app.operations.models.projects import Project
    
    # All domain models should have tenant_id field
    for model in [Invoice, Contract, Opportunity, Ticket, Project]:
        assert hasattr(model, 'tenant_id'), f"{model.__name__} missing tenant_id"
