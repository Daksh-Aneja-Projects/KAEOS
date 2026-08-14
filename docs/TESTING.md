# Testing

Back to the [README](../README.md). Related: [Benchmarks](BENCHMARKS.md) |
[Security model](SECURITY_MODEL.md)

## E2E Test Suite (441 tests across 30 files, live backend + real Ollama)

The full E2E suite exercises every functional surface against a running backend with real
seeded data - all 10 department brains and their AI agents, the 7-gate skill pipeline
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

The three newest departments (healthcare, lending, procurement) are covered in the unit lane
rather than here, because their gates are deterministic statutory checkers that need no live
backend and no model - see "Statutory checkers and the new departments" below.

## Current status

The end-to-end suite (441 tests) passes against both SQLite (local dev)
and **PostgreSQL 16 + pgvector** (the production data stack) with row-level security enforced.
CI runs the non-Ollama suite against Postgres+pgvector, so a bug SQLite silently tolerates is
caught automatically (this is real: a `NUMERIC`-returns-`Decimal` bug that passed on SQLite was
found and fixed exactly this way). Exact pass counts are run-dependent - a few tests exercise a
live LLM whose availability and output vary. On a fresh Postgres deploy the app self-bootstraps:
`init_db` creates the non-owner `kaeos_app` role, installs RLS on every tenant table, and
`assert_rls_effective` refuses to serve traffic if isolation isn't actually in force.

The Alembic chain (currently head **0044**) is applied end to end against that same real
pgvector/pg16 instance, not only SQLite, because the two disagree in ways that matter: Postgres
rejects a `boolean = integer` comparison SQLite happily evaluates (fixed in `0025`), and
`alembic_version.version_num` is `VARCHAR(32)`, so a revision id longer than 32 characters fails
at upgrade time rather than at review time. Two ids were shortened for exactly that reason. If you
add a migration, keep the revision id at or under 32 characters and run the chain on Postgres.

## Unit tests (816 tests)

```bash
cd backend
pytest tests/ -v --tb=short --ignore=tests/e2e
```

The unit lane is per-process in-memory SQLite, so it parallelizes safely across
cores with `pytest-xdist` (~2.4x on this suite). CI already passes `-n auto` here:

```bash
cd backend
pytest tests/ --ignore=tests/e2e -n auto
```

Do NOT add `-n auto` to the e2e lane: those tests share one live backend on :8001
and would collide under parallel workers.

`tests/acceptance/` (4 scenario tests: Decision Studio, evolution engine, genome intelligence,
recommendation intelligence) is collected by the same command; it is scenario-shaped rather than
unit-shaped, but it needs no live backend, so it runs in this lane.

### Statutory checkers and the new departments

The regulated verticals are gated by deterministic statutory checkers in
`app/compliance/checkers/` - pure functions, no LLM, no DB, auto-discovered by `@register`. That
makes them the cheapest tests in the repo, and they are tested exhaustively: a PASS, a BLOCK, and
the `NOT_APPLICABLE` / `ADVISORY` branch for every framework tag.

| Test file | Covers |
|-----------|--------|
| `test_compliance_checkers.py` | The registry itself: an unbacked tag returns `UNBACKED`, which is **blocking**, and a checker that raises is treated as a BLOCK. This is the fail-closed contract every other checker test relies on. |
| `test_compliance_healthcare.py` | `HIPAA_MINIMUM_NECESSARY`, `HIPAA_AUTHORIZATION`, `HIPAA_DEIDENTIFICATION`, `PART2` (42 CFR Part 2) |
| `test_healthcare_phi.py` / `test_healthcare_part2.py` | The PHI disclosure gate and the Part 2 consent gate as wired into the pipeline, fail-closed |
| `test_lending_checkers.py` | `ECOA` (Reg B adverse action), `FAIR_LENDING` (four-fifths / disparate impact), `TILA`, `FDCPA` |
| `test_lending_underwriting.py` | The underwriting service running against those gates for real, plus adverse-action notice content |
| `test_disparate_impact.py` | The four-fifths rule with a significance check, which replaces LLM opinion wherever cohort outcome data exists |
| `test_compliance_procurement.py` | `THREE_WAY_MATCH`, `SEGREGATION_OF_DUTIES`, `SPEND_AUTHORIZATION`, `OFAC_SANCTIONS` |
| `test_three_way_match.py` / `test_procurement_department.py` | PO / receipt / invoice reconciliation in Decimal money, and the source-to-pay approval gates end to end |
| `test_engineering_compliance.py` | `SOC2` (CC8.1 change management), `ISO27001`, `CHANGE_FREEZE` |

### Platform and commercial surfaces

| Test file | Covers |
|-----------|--------|
| `test_gl_posting.py` | Double-entry posting: balanced entries, period locks, reversals |
| `test_finance_fx_cashflow_aging.py` | Multi-currency GL: every line converts to the tenant base currency at post time, a reversal re-converts at the **original** entry date so base amounts offset exactly, and reporting aggregates `amount_in_base` |
| `test_metrics_timeseries.py` | The stored metric series: the rollup is idempotent per bucket, and a metric with no underlying data is not written at all rather than stored as a fabricated `0` |
| `test_ops_console.py` | The super-admin `/ops` console reading cross-tenant through the owner session, and the public `/status` endpoint |
| `test_branding.py` | White-label theming: defaults, admin-only writes, fail-closed validation (hex colours; `logo_url` must be http(s)), tenant scoping |
| `test_entitlements.py` | Plan entitlements (no-op self-hosted, enforced in managed cloud), metered execution rating, and idempotent Stripe webhook handling |
| `test_prompt_guard.py` | Prompt-injection screening: benign text stays quiet, payloads are detected, command spans are redacted, untrusted text is fenced |

## Frontend tests (67 tests across 9 files)

```bash
cd frontend
npm test          # vitest run
```

Vitest with jsdom, covering the shared primitives that every view depends on: `CountUp`,
`DomainIcon`, `ErrorBoundary`, `LiveBadge`, `Sparkline`, the `useFocusTrap` hook, and the
`departments` / `format` / `time` libraries. No backend needed.
