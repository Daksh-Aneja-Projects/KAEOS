# Testing

Back to the [README](../README.md). Related: [Benchmarks](BENCHMARKS.md) |
[Security model](SECURITY_MODEL.md)

## E2E Test Suite (441 tests across 30 files, live backend + real Ollama)

The full E2E suite exercises every functional surface against a running backend with real
seeded data - all 7 department brains and their AI agents, the 7-gate skill pipeline
(compliance / confidence / HITL gates), the full rule lifecycle (create -> validate -> clone ->
export/import -> simulate), auth & RBAC, the Agent Factory lifecycle, predictive / polymorphic /
federated / physics engines, platform config, cost governor & agent protocol, workforce
deployments & domain packs, webhooks, calendar, conflicts, and the executive layer.
LLM-dependent tests use a local Ollama instance (`qwen2.5-coder:7b` model) - no cloud keys needed.

```bash
# 1. Start the backend
cd backend
python -m uvicorn app.main:app --port 8001 --log-level warning

# 2. Seed all data (separate terminal, from backend/)
python -m scripts.seed_master

# 3. Start Ollama (for LLM-dependent tests)
ollama pull qwen2.5-coder:7b

# 4. Run full E2E suite
python -m pytest tests/e2e/ -v --tb=short

# No model at all? The deterministic fake-LLM lane covers the gate/pipeline
# logic (this is what CI runs; ~17 min for the whole suite):
#   KAEOS_FAKE_LLM=1 DEV_MODE=true ENVIRONMENT=ci python -m uvicorn app.main:app --port 8001 &
#   pytest tests/e2e -m "not ollama" -q

# Run a single test file
python -m pytest tests/e2e/test_02_hr_department.py -v

# Run tests that don't need Ollama (fast, no LLM calls)
python -m pytest tests/e2e/ -v -m "not ollama"
```

### E2E file map

```
tests/e2e/
+-- conftest.py                      # Shared fixtures (httpx client, has_ollama)
+-- test_01_company_brain.py
+-- test_02_hr_department.py
+-- test_03_finance_department.py
+-- test_04_legal_department.py
+-- test_05_sales_department.py
+-- test_06_support_department.py
+-- test_07_operations_department.py
+-- test_08_cross_functional.py
+-- test_09_agent_factory.py
+-- test_10_infrastructure.py
+-- test_11_executive_layer.py
+-- test_12_connectors_integrations.py
+-- test_13_auth_rbac.py
+-- test_14_skills_pipeline.py
+-- test_15_rules_lifecycle.py
+-- test_16_advanced_intelligence.py
+-- test_17_platform_infrastructure.py
+-- test_18_workforce_billing.py
+-- test_19_governance_operations.py
+-- test_20_domain_deep_actions.py
+-- test_21_live_connectors.py
+-- test_22_shock_scenarios.py
+-- test_23_coverage_gaps.py       # route gaps: HITL pairs, provenance, WS, admin keys
+-- test_24_byok_adaptive.py       # model probe -> ceiling -> gate adaptation
+-- test_25_engineering_department.py
+-- test_26_billing_reality_truth.py  # derived-not-fabricated regressions
+-- test_27_integration_catalog.py    # 22 adapters, graceful failure
+-- test_28_cross_tenant_denial.py    # RLS cross-tenant isolation proofs
+-- test_29_foundry_learning.py       # AI Foundry training-dataset layer
+-- test_30_agent_interface.py        # MCP endpoint + Company Skills File
```

## Current status

The end-to-end suite (441 tests) passes against both SQLite (local dev)
and **PostgreSQL 16 + pgvector** (the production data stack) with row-level security enforced.
CI runs the non-Ollama suite against Postgres+pgvector, so a bug SQLite silently tolerates is
caught automatically (this is real: a `NUMERIC`-returns-`Decimal` bug that passed on SQLite was
found and fixed exactly this way). Exact pass counts are run-dependent - a few tests exercise a
live LLM whose availability and output vary. On a fresh Postgres deploy the app self-bootstraps:
`init_db` creates the non-owner `kaeos_app` role, installs RLS on every tenant table, and
`assert_rls_effective` refuses to serve traffic if isolation isn't actually in force.

## Unit tests

```bash
cd backend
pytest tests/ -v --tb=short --ignore=tests/e2e
```
