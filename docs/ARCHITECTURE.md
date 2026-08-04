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
| **Department Brains** | Specialized AI reasoning engines per business function - HR, Finance, Legal, Sales, Customer Support, Operations (incl. procurement, vendors, QA), and Engineering & IT Ops (code review, deployments, incidents), each with domain agents that run through the gated pipeline | `/hr`, `/finance`, `/legal`, `/sales`, `/support`, `/operations`, `/engineering` |
| **Agent Factory** | Create, approve, compile, deploy, and orchestrate enterprise AI agents that all share the same organizational context - from a plain-English prompt | `/agents/blueprint*`, `/agents/deployed`, `/agents/debates`, `/agents/activity-feed` |
| **Decision Intelligence** | Evaluates business situations, generates options, scores cost / risk / impact, and recommends the best course of action - with adversarial debate before committing | `/reality/shock`, `/reality/decision`, `/simulation/what-if`, `/org-intelligence/*` |
| **Learning Engine** | Learns continuously from decisions and outcomes: confidence decay, Bayesian validation updates, execution feedback (L10), and learning modifiers that improve future recommendations | `/reality/learning`, `ConfidenceEngine`, `FeedbackEngine`, `EvolutionEngine` |
| **Enterprise Simulation** | "What-if" scenarios - **M&A integration, cyber incidents**, talent exodus, vendor/supply-chain failure, system outages, budget cuts, macro shocks. Blast-radius traversal runs over the live twin; the impact-scoring layer is a **parametric simulator over configurable causal archetypes** (tuned profiles, not learned from tenant data) | `/reality/shock`, `/reality/simulate`, `/10x/physics/simulate`, `/simulation/what-if` |
| **Governance & Provenance** | Every recommendation is explainable, traceable, and auditable - a hash-chained (tamper-evident) provenance ledger, fairness audits, red-team checks, and blocking HITL gates. Explainable by design, not a black box | `/provenance`, `/10x/quantum-events`, `/fairness/audit-log`, `/redteam`, `/hitl` |
| **Executive Command Center** | A real-time interface where leaders monitor the enterprise, inject business shocks, visualize downstream impact, and receive actionable recommendations in seconds | `/executive/*`, `/dashboard/cockpit`, `/reality/twin`, Reality Experience UI |

## System diagram

```
+----------------------------------------------------------------------+
|                         KAEOS Frontend                               |
|   React / TypeScript / 40 Pages / 7 Department Views                 |
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
|  |  Compliance -> Fairness -> Confidence -> HITL -> Debate ->    |   |
|  |  Execute (tiered BYOK routing: local Ollama or cloud via      |   |
|  |  LiteLLM) -> Provenance Ledger                                |   |
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

## Project structure

```
kaeos/
+-- backend/
|   +-- app/
|   |   +-- agents/
|   |   |   +-- runtime.py           # THE 7-gate pipeline (AgentExecutor): compliance,
|   |   |                            # fairness, confidence/HITL, debate, execute, audit
|   |   +-- api/
|   |   |   +-- routes/              # 34+ FastAPI route files
|   |   +-- core/
|   |   |   +-- auth.py              # JWT + API key auth
|   |   |   +-- config.py            # Settings (DEV_MODE, secret validation)
|   |   |   +-- seed.py              # Startup seeder (skills, rules, departments)
|   |   |   +-- middleware.py        # Rate limiting, tenant isolation, CORS
|   |   |   +-- database.py          # Async SQLAlchemy setup
|   |   |   +-- polystore/           # Dual-mode: VectorStore / GraphStore / CacheBus
|   |   +-- models/
|   |   |   +-- domain.py            # Core domain models (Skill, Rule, Execution, Signal...)
|   |   |   +-- events.py            # SystemEvent, WebhookSubscription
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
|   |   |   +-- domain_packs/packs/  # hr.yaml, finance.yaml, legal.yaml...
|   |   |   +-- runtime/
|   |   |       +-- department_runtime.py
|   |   +-- hr/                      # HR vertical (14 models, 7 agents, full API)
|   |   +-- finance/                 # Finance vertical
|   |   +-- legal/                   # Legal vertical
|   |   +-- sales/                   # Sales vertical
|   |   +-- support/                 # Support vertical
|   |   +-- operations/              # Operations vertical
|   |   +-- engineering/             # Engineering & IT Ops vertical
|   |       +-- models/              # core (services, engineers), delivery (PRs, deploys), incidents
|   |       +-- agents/              # code_review, incident, deploy_risk (+ gated_runner)
|   |       +-- api/v1/router.py
|   |       +-- seed.py
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
|   |   +-- pages/                   # 40 page components (most lazy-loaded by views/)
|   |   +-- views/                   # 7 department view composites
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
