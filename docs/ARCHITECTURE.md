# Architecture

Back to the [README](../README.md). Related: [Features](FEATURES.md) |
[API reference](API.md) | [Security model](SECURITY_MODEL.md) | [Testing](TESTING.md)

## Vision

KAEOS is building the AI Operating System for Companies.

Today's enterprises run on dozens of disconnected systems - Workday for HR, SAP for Finance,
Jira for Projects, ServiceNow for IT, Salesforce for Sales. Each system stores data, but none
truly understands how the entire organization works.

KAEOS creates a living **Company Brain** by building a real-time **Enterprise Twin** that models
employees, departments, capabilities, projects, vendors, goals, knowledge, risks, decisions, and
the relationships between them. On top of that twin sits a reasoning layer that predicts the
consequences of change, coordinates autonomous AI agents, and helps organizations make better
decisions **before problems become crises**.

**The moonshot:** to build a true **Company Brain** - an intelligent reasoning layer that sits
above every enterprise system, understands how the entire business operates, predicts the
consequences of change, coordinates autonomous AI agents, and helps organizations make better
decisions before problems become crises.

**The problem:** enterprise AI deployments fail because they require engineers to build every
workflow from scratch, and because each AI tool sees only one silo of the business. KAEOS inverts
this model: the system understands your organization from its signals, structures autonomous
agents around your existing processes, and operates continuously - with full audit trails and
human override at every step.

## The Eight Pillars

| Pillar | What it does | Where it lives in KAEOS |
|--------|--------------|-------------------------|
| **Company Brain** | A unified intelligence layer that understands the whole organization instead of isolated departments - rules, skills, signals, and a cross-domain knowledge graph with 5-dimensional confidence scoring | `/brain/overview`, `/rules`, `/skills`, `/topology/graph`, `/elicitation`, `/extraction` |
| **Department Brains** | Specialized AI reasoning engines per business function - HR, Finance, Legal, Sales, Customer Support, Operations, Engineering & IT Ops, plus three regulated verticals (Healthcare, Procurement & Sourcing, Banking & Lending), each with domain agents that run through the gated pipeline | `/hr`, `/finance`, `/legal`, `/sales`, `/support`, `/operations`, `/engineering`, `/healthcare`, `/procurement`, `/lending` |
| **Agent Factory** | Create, approve, compile, deploy, and orchestrate enterprise AI agents that all share the same organizational context - from a plain-English prompt | `/agents/blueprint*`, `/agents/deployed`, `/agents/debates`, `/agents/activity-feed` |
| **Decision Intelligence** | Evaluates business situations, generates options, scores cost / risk / impact, and recommends the best course of action - with adversarial debate before committing | `/reality/shock`, `/reality/decision`, `/simulation/what-if`, `/org-intelligence/*` |
| **Learning Engine** | Learns continuously from decisions and outcomes: confidence decay, Bayesian validation updates, execution feedback (L10), and learning modifiers that improve future recommendations | `/reality/learning`, `ConfidenceEngine`, `FeedbackEngine`, `EvolutionEngine` |
| **Enterprise Simulation** | "What-if" scenarios - **M&A integration, cyber incidents**, talent exodus, vendor/supply-chain failure, system outages, budget cuts, macro shocks. Blast-radius traversal runs over the live twin; the impact-scoring layer is a **parametric simulator over configurable causal archetypes** (tuned profiles, not learned from tenant data) | `/reality/shock`, `/reality/simulate`, `/10x/physics/simulate`, `/simulation/what-if` |
| **Governance & Provenance** | Every recommendation is explainable, traceable, and auditable - a signed, append-only, hash-chained provenance ledger (one HMAC scheme, per-tenant chains, DB-serialized appends, end-to-end verifier; pre-unification entries report as legacy), fairness audits, red-team checks, and blocking HITL gates. Explainable by design, not a black box | `/provenance`, `/10x/quantum-events`, `/fairness/audit-log`, `/redteam`, `/hitl` |
| **Executive Command Center** | A real-time interface where leaders monitor the enterprise, inject business shocks, visualize downstream impact, and receive actionable recommendations in seconds | `/executive/*`, `/dashboard/cockpit`, `/reality/twin`, Reality Experience UI |

## System diagram

```
+----------------------------------------------------------------------+
|                         KAEOS Frontend                               |
|   React / TypeScript / 52 Pages / 10 Department Views                |
|   Real-time WebSocket / SSE Streaming / Tailwind CSS                 |
+----------------------------------+-----------------------------------+
                                   |  REST + WebSocket + SSE
+----------------------------------v-----------------------------------+
|                    FastAPI Backend  (Python)                         |
|                                                                      |
|  +-------------+  +-------------+  +-------------+  +-----------+    |
|  | Auth / RBAC |  |  EventBus   |  |  WebSocket  |  | Scheduler |    |
|  | JWT / API   |  |  Redis      |  |  Manager    |  | APScheduler|   |
|  | Keys / OIDC |  |  Pub/Sub    |  |  Multi-     |  | Decay loop|    |
|  +-------------+  +-------------+  |  tenant     |  +-----------+    |
|                                    +-------------+                   |
|  +---------------------------------------------------------------+   |
|  |             7-Gate Skill Execution Pipeline                   |   |
|  |  Compliance (deterministic statutory checkers) -> Fairness -> |   |
|  |  Confidence -> HITL -> Debate -> Execute (tiered BYOK         |   |
|  |  routing: local Ollama or cloud via LiteLLM)                  |   |
|  |  -> Provenance Ledger                                         |   |
|  +---------------------------------------------------------------+   |
|                                                                      |
|  +-------------+  +-------------+  +-------------+  +-----------+    |
|  |  PreCog     |  |  Physics    |  |  Genome     |  |  Pattern  |    |
|  |  Engine     |  |  Engine     |  |  Compiler   |  |  Discovery|    |
|  +-------------+  +-------------+  +-------------+  +-----------+    |
|                                                                      |
|  +-------------------------------------------------------------+     |
|  |                   Workforce Layer                           |     |
|  |  11-State FSM / Domain Pack Marketplace / DepartmentRuntime |     |
|  |  Agent Factory / Blueprint State Machine / WorkforceGen     |     |
|  +-------------------------------------------------------------+     |
+----------------------------------+-----------------------------------+
                                   |
+----------------------------------v-----------------------------------+
|                         Polystore                                    |
|   PostgreSQL + pgvector  |  Redis  |  Neo4j  |  SQLite (dev)         |
+----------------------------------------------------------------------+
```

Notes on the auth box: single sign-on is OpenID Connect (Azure AD, Okta, Google, Auth0)
and SAML 2.0 (signature-verified, SP-initiated). See [Security model](SECURITY_MODEL.md).

The execute stage uses tiered BYOK routing (local Ollama or cloud providers via LiteLLM);
see [BYOK](BYOK.md) for the tier table and the measured confidence ceiling.

## Intelligence layer

| Engine | Description |
|--------|-------------|
| **PreCog Engine** | Reads external signals (market, regulatory, behavioral) and detects latent intent - triggering zero-prompt autonomous workflows without human input |
| **Enterprise Physics Engine** | Models causal laws across your organization. Runs shock simulations: "What happens to SLA compliance if we lose 3 engineers?" |
| **Genome Compiler** | Encodes your organization as an evolvable genome. Compiles live physics features (workforce stability, capability redundancy, delivery rate, vendor concentration, budget utilization) into trait scores. Live at `GET /genome/state` |
| **Evolution Engine** | Scores enterprise fitness across 9 sub-scores and derives structural optimizations from real weak signals - unverified rules, stopped agents, vendor concentration, recent failures. Live at `GET /evolution/state` |
| **Pattern Discovery Engine** | Mines unstructured signals for hidden workflow opportunities - surfacing automations no one asked for |
| **Digital Twin** | A living, physics-simulated graph of your entire organization - employees, capabilities, projects, vendors, and their relationships. Department territories are hue-coded, energy particles trace signal flow, and injected shocks propagate visibly: an expanding shockwave hits each impacted node in graph-distance order with a physical impulse |

## Compliance layer - deterministic statutory checkers

Gate 1 does not ask a language model whether an action is compliant. It runs **pure functions**.

`app/compliance/` is a small three-part package:

| Piece | Responsibility |
|-------|----------------|
| `base.py` | `CheckResult` / `CheckStatus` / `Finding` - the verdict shape every checker returns |
| `registry.py` | Framework tag -> checker binding, lazy `pkgutil` discovery, `run_checks()` |
| `checkers/` | One module per department, each self-registering via `@register(...)` |

The design rules that make it trustworthy:

- **Deterministic and LLM-free.** A checker is a pure function over a context dict. The same
  context always yields the same verdict, so a control can be unit-tested like any other code.
- **Fail-closed by construction.** A framework tag with **no** backing checker returns
  `UNBACKED`, which is **blocking**. An unbacked compliance claim can never read as satisfied -
  that was precisely the hole in a guess-based path. A checker that **raises** is treated as
  `BLOCK`: a broken control is not a passing control.
- **Auto-discovered, no central edit.** Dropping a new module into `checkers/` registers its
  frameworks at import. A module that fails to import is logged and skipped rather than taking
  the app down.
- **Self-describing.** `list_frameworks()` returns every framework the platform can actually
  verify, with its title and statutory citation - the honest answer to "which of these
  compliance badges are real versus a label".

Frameworks backed today, by department module:

| Module | Frameworks |
|--------|-----------|
| `healthcare.py` | `HIPAA_MINIMUM_NECESSARY`, `HIPAA_AUTHORIZATION`, `HIPAA_DEIDENTIFICATION`, `PART2` (42 CFR Part 2) |
| `lending.py` | `ECOA` (Reg B adverse action), `FAIR_LENDING` (four-fifths / disparate impact), `TILA`, `FDCPA` |
| `procurement.py` | `THREE_WAY_MATCH`, `SEGREGATION_OF_DUTIES`, `SPEND_AUTHORIZATION`, `OFAC_SANCTIONS` |
| `engineering.py` | `SOC2` (CC8.1 change management), `ISO27001`, `CHANGE_FREEZE` |
| `finance.py` | `SOX` |
| `hr.py` | `EEOC`, `FLSA`, `I9` |
| `legal.py` | `CONFLICT_OF_INTEREST`, `LEGAL_HOLD`, `RETENTION_SCHEDULE`, `CONTRACT_CLAUSE` |
| `support.py` | `PII_REDACTION`, `CALL_RECORDING_CONSENT`, `SLA_BREACH` |
| `operations.py` | `CHANGE_MANAGEMENT`, `INCIDENT_POSTMORTEM`, `BACKUP_RETENTION` |
| `crm.py` | `GDPR`, `CCPA`, `TCPA`, `DSAR` |

The three regulated verticals (Healthcare, Procurement, Lending) are built around this layer
rather than bolted onto it: the hard block lives in the deterministic service, and the gated
agent produces the plain-English "why" afterwards.

## Operator and commercial surfaces

Four surfaces sit outside the per-tenant product API and are worth calling out because their
trust boundaries differ:

| Surface | Auth | What it is |
|---------|------|-----------|
| `GET /status` | **None (public)** | Liveness for load balancers and uptime checks: db / redis / llm reachability, app version, uptime seconds. Returns **503** when the database is unreachable, since that is the only critical dependency. It reuses `main._probe_dependencies()` rather than forking it |
| `/api/v1/ops/*` | Super-admin (`ADMIN_SECRET` dependency) | The operator console: `tenants`, `tenants/{id}`, `overview`. Cross-tenant reads go through the owner/maintenance session, which is the only place in the codebase that legitimately crosses the RLS boundary |
| `/api/v1/branding` | GET any authed tenant user, PUT admin | White-label theming (product name, primary/accent colour, logo, login subtitle). Validation is fail-closed: colours must be `#rrggbb`, and `logo_url` must be an absolute `http(s)` URL with a host, so `javascript:` / `data:` payloads can never reach the login shell |
| `/api/v1/metrics/timeseries` | Tenant user | The **stored** metric series (see below), so dashboards and Time Machine read a recorded series instead of reconstructing one per request |

`/status` deliberately does **not** expose the platform safe-autonomy rate. It is a business
metric, and its cross-tenant aggregate is an unindexed full scan (`skill_executions` is indexed
tenant-id-leading), which would make an auth-free endpoint a DoS amplifier. That number lives on
the super-admin-gated `/ops/overview` instead.

## Time-series metrics store

Metrics used to be recomputed from raw executions on every read. They are now **recorded**:

- `ts_metric_samples` stores `(tenant_id, metric_key, interval, bucket_start, value)`.
- A **leader-guarded** rollup runs on the existing scheduler, idempotent per bucket, snapshotting
  each active tenant's `safe_autonomy_rate`, `execution_volume` and `cost_usd`.
  Interval: `METRICS_ROLLUP_INTERVAL_MINUTES` (default 60).
- **Honesty contract:** a metric with no underlying data in a bucket is **not written at all**.
  There is no fabricated `0`. `cost_usd` keys off whether cost events exist rather than off
  execution volume, because a gate-blocked action burns real tokens without ever producing an
  execution row. A query over an empty window returns an empty series plus a note saying so.

## Multi-currency general ledger

The finance vertical posts a real multi-currency ledger rather than assuming one currency:

- `fin_fx_rates` holds per-tenant rates; `fin_journal_lines.amount_in_base` holds the converted
  magnitude of each line's single non-zero side.
- Every journal line converts to the tenant base currency **at post time**
  (`FINANCE_BASE_CURRENCY`, default `USD`). A foreign line with no rate on or before its entry
  date is **refused**, so the ledger never holds an unconverted amount masquerading as base.
- All GL reporting - trial balance, income statement, balance sheet, cash flow - aggregates
  `amount_in_base`, falling back to the native column only for pre-FX historic rows, instead of
  summing native debit/credit across mixed currencies.
- A **reversal re-converts at the original entry date**, not today, so base amounts offset to
  exactly zero. Reversing at today's rate would leave a residual base-currency imbalance on any
  multi-currency entry.

## Project structure

```
kaeos/
+-- backend/
|   +-- app/
|   |   +-- agents/
|   |   |   +-- runtime.py           # THE 7-gate pipeline (AgentExecutor): compliance,
|   |   |                            # fairness, confidence/HITL, debate, execute, audit
|   |   +-- api/
|   |   |   +-- routes/              # 60+ FastAPI route files, incl. ops.py (operator
|   |   |                            # console + public /status) and branding.py
|   |   +-- compliance/              # Deterministic statutory checkers (see above)
|   |   |   +-- base.py              # CheckResult / CheckStatus / Finding
|   |   |   +-- registry.py          # @register, lazy discovery, fail-closed run_checks
|   |   |   +-- checkers/            # One module per department, self-registering
|   |   +-- core/
|   |   |   +-- auth.py              # JWT + API key auth
|   |   |   +-- config.py            # Settings (DEV_MODE, secret validation)
|   |   |   +-- seed.py              # Startup seeder (skills, rules, departments)
|   |   |   +-- workforce_seed.py    # Org-graph backbone: real WorkforceGenerator per pack
|   |   |   +-- middleware.py        # Rate limiting, tenant isolation, CORS, CSP
|   |   |   +-- database.py          # Async SQLAlchemy setup
|   |   |   +-- polystore/           # Dual-mode: VectorStore / GraphStore / CacheBus
|   |   +-- models/
|   |   |   +-- domain.py            # Core domain models (Skill, Rule, Execution, Signal...)
|   |   |   +-- events.py            # SystemEvent, WebhookSubscription
|   |   |   +-- metrics_ts.py        # MetricSample (ts_metric_samples)
|   |   |   +-- branding.py          # TenantBranding (white-label theming)
|   |   +-- services/
|   |   |   +-- skill_executor.py    # Runs skill steps AFTER the gates clear; the gates
|   |   |   |                        # themselves live in app/agents/runtime.py
|   |   |   +-- consequence.py       # Shared always-HITL (high-consequence) detection
|   |   |   +-- hitl_manager.py      # HITL: DB is source of truth; Redis/memory cache carries resume payloads
|   |   |   +-- event_bus.py         # EventBus + WebSocket broadcast
|   |   |   +-- llm_router.py        # LiteLLM routing, per-tenant BYOK, capability ceiling
|   |   |   +-- llm_support.py       # Probes + embedding cache + router exceptions (split from llm_router)
|   |   |   +-- llm_simulation.py    # Deterministic degraded-mode completions (split from llm_router)
|   |   |   +-- model_probe.py       # BYOK self-calibration battery
|   |   |   +-- json_utils.py        # Tolerant LLM JSON parsing (use everywhere)
|   |   |   +-- metrics_timeseries.py # Leader-guarded hourly rollup into ts_metric_samples
|   |   |   +-- live_connectors.py   # Credentialed live sync + encryption
|   |   |   +-- vendor_adapters/     # 17 vendor adapters (+5 core in live_connectors = 22); package split by category: base/devops/itsm/hr_finance/collaboration/registry
|   |   |   +-- precog_engine.py     # Zero-prompt ambient intelligence
|   |   |   +-- enterprise_physics_engine.py
|   |   |   +-- genome_compiler.py
|   |   |   +-- pattern_discovery_engine.py
|   |   +-- workforce/
|   |   |   +-- api/                 # Departments, deployment, packs, processes
|   |   |   +-- deployment/
|   |   |   |   +-- state_machine.py # 11-state FSM
|   |   |   |   +-- studio.py        # Deployment pipeline owner
|   |   |   |   +-- integration_mapper.py
|   |   |   +-- domain_packs/packs/  # 10 packs: hr, finance, legal, sales, support,
|   |   |   |                        # operations, engineering, healthcare,
|   |   |   |                        # procurement, lending
|   |   |   +-- runtime/
|   |   |       +-- department_runtime.py
|   |   +-- hr/                      # HR vertical (14 models, 7 agents, full API)
|   |   +-- finance/                 # Finance vertical
|   |   +-- legal/                   # Legal vertical
|   |   +-- sales/                   # Sales vertical
|   |   +-- support/                 # Support vertical
|   |   +-- operations/              # Operations vertical
|   |   +-- engineering/             # Engineering & IT Ops vertical
|   |   |   +-- models/              # core (services, engineers), delivery (PRs, deploys), incidents
|   |   |   +-- agents/              # code_review, incident, deploy_risk (+ gated_runner)
|   |   |   +-- api/v1/router.py
|   |   |   +-- seed.py
|   |   +-- healthcare/              # Healthcare vertical (HIPAA / 42 CFR Part 2)
|   |   |   +-- models/core.py       # hlth_* encounters, disclosures, consent, tasks
|   |   |   +-- agents/              # intake, coding, phi_guard, prior_auth (+ gated_runner)
|   |   |   +-- services/            # phi_disclosure, analytics
|   |   +-- lending/                 # Banking & Lending vertical (ECOA / TILA / FDCPA)
|   |   |   +-- models/core.py       # lnd_* applications, decisions, adverse actions
|   |   |   +-- agents/              # intake, underwriter, adverse_action (+ gated_runner)
|   |   |   +-- services/            # underwriting, analytics
|   |   +-- procurement/             # Procurement & Sourcing vertical (source-to-pay)
|   |       +-- services/            # source_to_pay: the deterministic three-way match
|   |       +-- agents/gated_runner.py  # Sourcing + SpendGuard, control work first, then gated LLM
|   |       +-- api/v1/router.py     # Reuses operations.procurement + finance AP models
|   +-- alembic/versions/            # Migration chain, head 0049 (see Data layer & migrations)
|   +-- scripts/
|   |   +-- seed_master.py           # Master seeder - the only entry point you need
|   |   +-- seed_agent_factory.py    # Agent Factory blueprints + agents
|   |   +-- seed_infrastructure.py   # Model registry, prompts, cost governor
|   |   +-- seed_integrations.py     # External intelligence signals
|   |   +-- security_audit.py        # Security posture audit
|   |   +-- load_test.py             # Load/perf harness
|   +-- tests/
|   |   +-- e2e/                     # E2E suite (live backend + real Ollama) - see docs/TESTING.md
|   +-- requirements.txt
|   +-- Dockerfile
|   +-- pytest.ini
+-- frontend/
|   +-- src/
|   |   +-- pages/                   # 52 page components (most lazy-loaded by views/)
|   |   +-- views/                   # 10 department view composites + settings composites
|   |   +-- hooks/                   # useWebSocket, useAuth, useTheme
|   |   +-- api/                     # Typed API client: client.ts barrel re-exporting http.ts + types.ts + endpoints/ (split by domain)
|   |   +-- context/                 # AuthContext, ThemeContext
|   +-- Dockerfile
|   +-- package.json
|   +-- vite.config.ts
+-- docs/                            # Architecture, API, security, testing, limitations...
+-- .env.example                     # All env vars documented
+-- .gitignore
+-- docker-compose.yml               # Full stack: API + DB + Redis + Prometheus + Grafana
+-- prometheus.yml
+-- CONTRIBUTING.md
+-- CODE_OF_CONDUCT.md
+-- SECURITY.md
+-- NOTICE                           # Required attributions (Apache 2.0)
+-- LICENSE
```

## Data layer & migrations

The schema is Alembic-managed and currently runs to **head 0049**. Recent additions, all
additive and inspector-guarded (safe to re-run against a partially migrated database), with
RLS enabled on PostgreSQL:

| Revision | What it adds |
|----------|--------------|
| `0040_fin_fx_rates` | Multi-currency GL: `fin_fx_rates` + `fin_journal_lines.amount_in_base` |
| `0041_healthcare_tables` | Healthcare vertical (`hlth_*`) |
| `0042_lending_vertical` | Lending vertical (`lnd_*`) |
| `0043_metrics_timeseries` | `ts_metric_samples` |
| `0044_tenant_branding` | `brand_tenant_branding` |
| `0045_engineering_tables` | `eng_*` service/delivery/incident/on-call/CI tables |
| `0046_support_fixes` | `sup_agents.avg_csat` retyped to numeric |
| `0047_hc_compliance` | `hlth_compliance_reports`, `hlth_compliance_violations` |
| `0048_loan_servicing` | `lnd_serviced_loans`, `lnd_collection_cases` |
| `0049_ops_work_orders` | `ops_work_orders` + agent-decision advisory columns |

Two deployment lessons are baked into the chain and are worth knowing before you add a revision:

- **Revision ids must stay at 32 characters or fewer.** `alembic_version.version_num` is
  `VARCHAR(32)`. Two ids were renamed for exactly this reason; a longer id passes locally and
  then fails on first upgrade against a real database.
- **PostgreSQL will not compare a boolean to an integer.** A `boolean = integer` comparison in
  `0025` was fixed because SQLite tolerated it and PostgreSQL rejected it outright.

The chain is validated against a real pgvector / PostgreSQL 16 instance, not only against the
SQLite dev database, precisely because those two divergences are invisible on SQLite.

## Startup sequence - why the org graph is never empty

The Neural Map, Reality Experience, Org Pulse, Departments hub and Command Center all render the
organization graph. Without a backbone of capabilities and agents they render an empty
organization, which reads as a broken product rather than an empty tenant.

`app/core/workforce_seed.py` runs as a startup step, after the departments are seeded and the
domain packs are synced. It does **not** fabricate rows. It drives the product's own deterministic
deployment path - `WorkforceGenerator.generate_department_structure()` followed by
`deploy_agents()` - against each synced pack, which is exactly what happens when a real customer
deploys that department. Capabilities, agent names, personas and compliance tags therefore come
from the pack YAML, so the demo organization and a customer organization are built the same way
and cannot drift apart.

It is LLM-free and fully deterministic, and idempotent at three levels: a department that already
has agents is skipped by the generator, only missing capability slugs are created, and a
deployment is reused per (tenant, pack). It never raises - failing to enrich the graph must not
stop the application from booting.

## Performance & latency

KAEOS runs governance on **real models** (local Ollama `qwen2.5-coder:7b`; simulated
output is only a fail-closed fallback), so latency is optimized without weakening a
gate or changing any decision's reasoning:

- **Nothing blocks on a long model call.** Missions execute in a **background runner**
  (own DB session, per-mission guard, stale-step crash recovery) - `advance` returns in
  ~0.2s and the UI polls for live progress instead of holding a multi-minute request.
- **Repeat work is eliminated, not approximated.** An **embedding cache** returns
  byte-identical vectors and skips repeat provider calls; the frontend **dedupes
  concurrent identical GETs**; the debate gate **bounds generation** to its short JSON
  verdict.
- **The hot analytics reads are indexed.** Composite indexes on
  `skill_executions (tenant_id, started_at)` and `cost_events (tenant_id, timestamp)`
  turn the safe-autonomy / time-machine / causal / regulatory / cost queries into
  covering-index seeks.
- **It is measured, not guessed.** Every gate transition records its wall-time lap:
  execution results carry `stage_timings` + `pipeline_ms`, the `gate_event` WebSocket
  payload carries per-gate `ms`, and `GET /metrics/latency` aggregates model-call
  latency by tier/model (avg/p50/p95/max from metered CostEvent rows) plus per-gate
  wall-time of recent executions. Per-model-tier average latency is also surfaced
  live in the Executive Cockpit.
- **The debate earns its length.** The adversarial debate arbitrates after the first
  proposer/advocate exchange and runs a second exchange ONLY when the verdict is
  contested (arbitrator confidence in the 0.5-0.8 band). A decisive debate resolves
  in 3 sequential reasoning calls instead of 5; a contested one keeps the full
  two-turn scrutiny. No gate is weakened - only the repeat of an already-heard
  argument is skipped.
- **Independent gates run concurrently.** Compliance (Gate 1) and fairness (Gate 2)
  are independent of each other; when both apply they run under `asyncio.gather`,
  with compliance-BLOCKER verdict ordering preserved. Cross-domain debate
  perspectives are gathered concurrently too.
- **Back-navigation is instant.** The API client keeps a 15s stale-while-revalidate
  cache for GETs: a remounted page renders from the last response while a background
  refetch keeps it live; any mutation flushes the cache. The TTL sits under the 20s
  live-refresh convention, so polling pages still hit the network every tick.

- **One optimization was measured and then rejected.** Splitting the gate
  pipeline across a small "nano" model and the resident 7b looks like an obvious
  win, and on a 6GB GPU it is net-negative: Ollama keeps one model resident by
  default, loading the helper evicts the 7b rather than co-residing with it, and
  the resulting swap on every tier switch costs more than the smaller model
  saves. The nano tier definition stays for hardware with the VRAM headroom, but
  nothing routes to it by default. Compliance-verdict caching was also
  deliberately not done: a verdict depends on context, so caching it could
  rubber-stamp a changed context.
