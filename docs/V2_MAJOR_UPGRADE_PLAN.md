# KAEOS v2.0 — The Self-Improving Autonomy Platform
### Definitive Major-Upgrade Plan (all layers)

> **Authors**: Daksh Aneja + Claude (co-founder), acting as an L10 review team
> **Baseline**: v1.1.2 (2026-07-21) — 7-domain, security-hardened, ~50k LOC backend / ~20k LOC frontend
> **Target**: v2.0.0
> **North-star metric**: **safe-autonomy-rate** — the fraction of agent actions executed safely without human intervention
> **Method**: This plan is grounded in five parallel L10 layer-audits (backend, frontend, AI Foundry, governance, infra/ops). Every claim below cites `file:line` evidence gathered from the current tree. Tasks are framed to **copy proven in-repo patterns**, not to invent APIs.

---

## Implementation status (living)

Executed in tested, individually-committed increments on `main`. Backend unit suite green throughout; frontend build + Vitest green.

| Phase | Status | Delivered |
|---|---|---|
| 1 — Foundation Discipline | ✅ complete | create_all gated; append-only state + migration 0006; 27 missing tables registered (216-table baseline); fake graph deleted, real-graph fitness/scorecard; RLS-safe prod compose |
| 2 — Safety Hardening | ✅ complete | default-deny + enforcement test; HITL approver integrity; structural fairness gate; real audit-datum gate; PII fail-closed; vector-embedding erasure |
| 3 — Durable/Scalable Exec | ◑ partial | deployment crash-recovery reaper (done). Durable job queue, k8s/Helm, shared Redis limiter, secrets mgr, observability-on, CD → remaining |
| 4 — AI Foundry closed loop | ◑ partial | continuous mining automation (4D, done). Wire orphaned catalog (4A), pluggable trainer (4C), multi-objective eval (4E) → remaining |
| 5 — Safe-autonomy-rate | ✅ core | live computed metric + explainable breakdown + per-skill + time-series at `GET /metrics/safe-autonomy`. Materialized rollup/alerts → optional follow-up |
| 6 — Frontend v2 | ◑ partial | Vitest+RTL harness wired to CI (done). TanStack Query, OpenAPI codegen, client resilience, App.tsx decomposition → remaining |
| 7 — Verification & Release | ◑ ongoing | full regression each milestone; always-on Copilot verified live. Full-fidelity e2e + release tag → remaining |

Also shipped: the **always-on KAEOS Copilot** (persistent dock, real auth, fixed SSE), verified end-to-end in a running browser.

---

## The Thesis (why this is the right v2.0)

KAEOS's crown jewel is **real, production-grade governance**: the 7-gate `AgentExecutor` pipeline is genuinely wired end-to-end (`backend/app/agents/runtime.py:215-447`), RLS is fail-closed and boot-verified (`core/rls.py`, `main.py:127-131`), cost metering is live (`llm_router.py:455-496`), and the AI Foundry eval→gated-promotion loop is **honest and ~70% real** (`services/foundry/model_evolution.py`) with a deliberate "no fake trainer" stance.

The obvious v2.0 headline is the **AI Foundry closed loop** — a factory that mines governed executions, manufactures improved models, evaluates them deterministically, and promotes them under human gate. It is the natural evolution of the platform and the strongest sales narrative.

**But you cannot responsibly accelerate autonomy on top of a substrate that still has:** opt-in safety gates (`runtime.py:255-256, 338-339`), a spoofable HITL approver (`hr/api/v1/router.py:309-350`), a checkbox "audit" gate (`compliance.py:97-106`), fire-and-forget background execution that loses in-flight work on any restart (`workforce/deployment/studio.py:30`), and a production deployment artifact that **silently defeats RLS** by running the app as DB owner (`backend/docker-compose.prod.yml:24`).

**Therefore v2.0 = "The Self-Improving Autonomy Platform":** we *earn the right* to ship the Foundry headline by first hardening the safety + ops substrate, then we make **safe-autonomy-rate** a first-class, instrumented, dashboarded number — which is simultaneously the product's control loop and its enterprise sales artifact.

**Phase dependency spine:**
```
Phase 0  Ground Truth  ──►  Phase 1  Foundation Discipline
                                 │
                                 ▼
                          Phase 2  Safety Hardening ──► Phase 3  Durable/Scalable Execution
                                                              │
                                                              ▼
                                                       Phase 4  AI Foundry Closed Loop  ◄── HEADLINE
                                                              │
                                                              ▼
                                                       Phase 5  Safe-Autonomy-Rate metric
                                                              │
                                                              ▼
                                                       Phase 6  Frontend v2 (surface it)
                                                              │
                                                              ▼
                                                       Phase 7  Verification & Release
```

---

## Phase 0 — Ground Truth & Allowed-APIs (READ FIRST, every phase)

Consolidated real-vs-stub map. **Preserve the REAL; do not re-touch it except to extend. Attack the DEBT.**

### ✅ PRODUCTION-REAL (crown jewels — extend, never rewrite)
| Capability | Evidence | Note |
|---|---|---|
| 7-gate AgentExecutor | `agents/runtime.py:215-447` | Compliance→Fairness→Confidence/HITL→Debate→Execute→Audit, all real |
| LLM gateway (BYOK) | `services/llm_router.py:146-200, 317-418` | LiteLLM, per-tenant keys, retry + circuit breaker, fallback chains |
| Cost metering | `llm_router.py:455-496`, read-back `skill_executor.py:487-524` | 1 `CostEvent` per call, `litellm.cost_per_token` |
| Budget gate | `llm_router.py:420-453` | BLOCK/DEGRADE before dispatch |
| PII egress scrub | `llm_router.py:510-554` | Presidio + structured backstop (⚠ fails **open** — see Phase 2E) |
| Capability probe → confidence ceiling | `model_probe.py:105-182` → `runtime.py:289-297` | Simulated model scores 0.0 |
| Polystore (all 3 stores, both backends) | `core/polystore/{vector_store,cache_bus,graph_store}.py` | pgvector / Neo4j / Redis all real, `get_*()` selectors |
| AI Foundry eval + gated promotion | `services/foundry/{dataset_builder,model_evolution}.py` | Deterministic token-F1, no-LLM-judge, simulated-guard hard-blocks promotion |
| RLS isolation | `core/rls.py:62-76`, binding `core/database.py:106-124`, boot assert `main.py:127-131` | Fail-closed, single binding point |
| GDPR erasure / retention | `services/privacy_erasure.py`, `api/routes/privacy.py` | Admin-gated, audit-logged (⚠ coverage gaps — Phase 2E) |
| Tamper-evident ledger | `services/quantum_ledger.py:24-94` | SHA3-512 hash chain (⚠ global ordering — Phase 2D) |
| Leader election | `services/leader_lock.py` | Redis SET NX + Postgres advisory fallback |
| Config fail-fast | `core/config.py:188-223`, `main.py:70-107` | Refuses insecure/DEV_MODE-in-prod boot |
| Real-data pipeline | `scripts/onboard_real_company.py`, `benchmark/real_data/` | 7 Kaggle domains → `tenant_realco` (raw data gitignored) |

### 🔴 DEBT (the v2.0 work surface)
| # | Debt | Evidence | Phase |
|---|---|---|---|
| D1 | Fake "Neo4j" graph — in-memory JSON, misnamed, live consumers | `services/graph/neo4j_client.py:16,47-66`; consumers `impact_engine.py:11`, `scorecard_engine.py:11` | 1B |
| D2 | No migration discipline — `create_all`-driven; 75 tables, 5 migrations, zero `op.create_table` | `core/database.py:245`, `alembic/versions/0001_baseline_schema.py:50` | 1A |
| D3 | **Prod compose runs app as DB owner → RLS inert** | `backend/docker-compose.prod.yml:24` vs `main.py:127-131` | 1C |
| D4 | RBAC: no default-deny + two divergent role vocabularies | `models/auth.py:17-20` vs `core/tenant.py:57,137`; ungated mutation `reality.py:227,342` | 2A |
| D5 | HR HITL trusts client-supplied approver (spoofable) | `hr/api/v1/router.py:309-350`, `router.py:59-61` | 2B |
| D6 | Fairness/Debate gates opt-in via context flags | `runtime.py:255-256, 338-339`; `fairness_engine.py:32-34` | 2C |
| D7 | Gate 6 "Audit" is a checkbox, verifies nothing persisted | `compliance.py:97-106` | 2D |
| D8 | Provenance: global timestamp ordering, no scheduled verify | `quantum_ledger.py:48-53`, `provenance.py:87` | 2D |
| D9 | PII scrubber fails **open** | `llm_router.py:545,595` | 2E |
| D10 | Erasure skips blobs/embeddings/backups | `privacy_erasure.py:11-22` | 2E |
| D11 | Fire-and-forget background exec loses in-flight work | `workforce/deployment/studio.py:30` | 3A |
| D12 | No orchestration; per-process rate limiter | `main.py:294-296` | 3B |
| D13 | Secrets = plaintext `.env`; `SECRET_KEY` overloaded (JWT + connector encryption) | `.env.example:11-13`; no Vault/SOPS | 3C |
| D14 | Observability off-by-default; no OTLP exporter shipped; no dashboards/alerts | `config.py:41`, `telemetry.py:26-30`, empty `prometheus.yml` rule_files | 3D |
| D15 | No CD; image unscanned; `security-scan` non-blocking; actions on mutable tags; ship 3.11 vs test 3.12 | `.github/workflows/ci.yml:132-147`, `backend/Dockerfile:1` | 3E |
| D16 | AI Foundry: no trainer, no automation, orphaned registry/canary/prompt-versioning, split tier taxonomy | `model_management.py:139-151, 214-259` (orphaned); `llm_router.py:114` (3 tiers) vs `infrastructure.py:24-28` (4 tiers) | 4 |
| D17 | Frontend: 0 tests, no server-state lib (50+ dup fetch blocks), `any` at API boundary, monolithic `App.tsx` (775 lines), thin a11y | `frontend/package.json` (no test script), `hooks/useApi.ts` used in 2 files, `client.ts:1029-1108` | 6 |
| D18 | `state_service` "snapshots" mutate in place (no temporal history) | `services/state/state_service.py:52-63` | 1A (schema) / opportunistic |
| D19 | Dead `fitness_calculator.py` simulated placeholder | `services/evolution/fitness_calculator.py:4,26-101` | Delete in 1B sweep |

### Anti-patterns to forbid across ALL phases
- ❌ Do **not** add a fake trainer, fake eval, or any simulated data that isn't hard-gated behind `settings.simulated_llm_allowed` — the honesty stance (`model_evolution.py:18-21`, `llm_router.py:569-576`) is a core asset.
- ❌ Do **not** introduce `create_all` as a new schema authority (Phase 1A makes Alembic the single source of truth).
- ❌ Do **not** run app code as DB owner in any environment (breaks RLS).
- ❌ Do **not** trust caller-supplied identity/flags for governance decisions (approver, fairness applicability).
- ❌ Do **not** add `request<any>` API methods on the frontend (Phase 6B generates types).

---

## Phase 1 — Foundation Discipline
> **Goal**: Make the ground safe to build on. Cheap, high-leverage, de-risks every later phase.

### 1A — Real Alembic migration chain (D2, D18)
**What to implement (copy-oriented):**
1. Stop using `Base.metadata.create_all` as the production schema authority. In `core/database.py:245`, gate `create_all` to **dev/test only** (`settings.is_sqlite`); production schema comes exclusively from `alembic upgrade head`.
2. Regenerate a clean **autogenerated baseline** from the 75 models: configure `alembic/env.py` `target_metadata = Base.metadata`, run `alembic revision --autogenerate -m "v2_baseline"`, verify it reproduces the current DB, then make it the new `0001`. Keep the old raw-SQL `0002–0005` as a documented legacy re-stamp path (pattern already exists: `docs/DEPLOYMENT.md:41-46`).
3. Add a temporal-history migration for `state_service` (D18): introduce append-only state snapshots instead of in-place mutation (`state_service.py:52-63`) — the "Enterprise Twin" claim requires it.

**Docs/patterns to follow**: existing raw-SQL migrations `alembic/versions/0002–0005`; drift gate `scripts/check_migration_drift.py` (already in CI, `ci.yml:111`).
**Verification**: `alembic upgrade head` on empty Postgres reproduces the schema `create_all` would; `grep -r "create_table(" alembic/versions/` now returns matches; `check_migration_drift` passes; round-trip `upgrade head` → `downgrade -1` → `upgrade head` clean.
**Anti-pattern guard**: no `create_all` on the prod path; every future model change ships a migration.

### 1B — Graph consolidation (D1, D19)
**What to implement:**
1. Delete `services/graph/neo4j_client.py` (the misnamed in-memory fake, `:16,47-66`) and the dead `services/evolution/fitness_calculator.py` (`:4`).
2. Migrate live consumers (`impact_engine.py:11`, `scorecard_engine.py:11`, `synthetic/enterprise_generator.py:13`) from `graph_service.py` to the **real** `core/polystore/graph_store.py` via `get_graph_store()` (`graph_store.py:248`).
3. Wire `scorecard_engine.py:37` (D3-placeholder) to real graph queries now that the real store is the only path.

**Verification**: `grep -r "services.graph" backend/app` returns zero; `grep -ri "mock\|in-memory" backend/app/services/graph` returns nothing (dir gone); scorecard endpoint returns graph-derived data.
**Anti-pattern guard**: one graph abstraction only — `get_graph_store()`.

### 1C — Correct production deployment artifact (D3)
**What to implement:**
1. Rewrite `backend/docker-compose.prod.yml` to the **non-owner** pattern already correct in `docker-compose.staging.yml:55-62`: app connects as `kaeos_app`, DDL/migrations use a separate `KAEOS_OWNER_DB_URL`.
2. Collapse the three divergent compose files into **one parameterized definition** (env-driven) so dev/staging/prod cannot drift on the security model again.
3. Standardize the entrypoint on `start-prod.sh` (`alembic upgrade head` → gunicorn) across environments; document the owner-URL override for migrations (`docs/RUNBOOK.md:3-25`).

**Verification**: prod stack boots and **passes** `assert_rls_effective()` (`main.py:127-131`); `scripts/verify_rls.py` green; a cross-tenant read from an app-role session returns nothing.
**Anti-pattern guard**: CI job asserts no compose file sets `DATABASE_URL` to an owner role.

---

## Phase 2 — Safety Substrate Hardening
> **Goal**: Earn the right to accelerate autonomy. Every gap here is a hole in the safe-autonomy-rate story.

### 2A — RBAC unification + router-level default-deny (D4)
- Collapse the two role vocabularies (`ADMIN/ANALYST/VIEWER` in `models/auth.py:17-20` vs `viewer/operator/admin` in `core/tenant.py:57`) into **one** hierarchy; keep the hierarchy semantics from `tenant.py:227-251` (privilege-level compare), delete the exact-match `auth.py:43-52` variant.
- Move to **default-deny at the router**: a base dependency requires an authenticated role on every route; public routes opt *out* explicitly. Audit all 37 routers; fix confirmed ungated mutations (`reality.py:227,342`) and sweep for others.
- **Copy** the correct gate: `api/routes/skills.py:90-95`, `api/routes/privacy.py:39-69`.
**Verification**: a test enumerates every mutating route and asserts a role dependency is present; VIEWER token is rejected on all mutations.

### 2B — HITL approver integrity + single HITL system (D5)
- Replace client-supplied `HITLDecision.approver` (`hr/api/v1/router.py:59-61, 309-350`) with the authenticated-principal pattern `_approver_identity(tenant)` proven in `api/routes/hitl.py:11-23`.
- Converge the two HITL systems (DB-backed `hitl_manager.py` vs HR-domain) onto the core `hitl_manager` so there is one approval path, one non-repudiation guarantee.
**Verification**: `test_retention_and_erasure`-style test asserts the recorded approver equals the JWT subject, not the request body; spoofed `approver` in body is ignored.

### 2C — Structural gate invocation (D6)
- Make fairness/debate applicability **derived**, not opt-in: instead of trusting `context["requires_fairness_assessment"]` / `_skill_obj` (`runtime.py:255-256, 338-339`), classify the skill/data (PII / protected-class / high-consequence tags already in `config.py:61-64`) and invoke the gate when the classification demands it.
- **Copy** the fail-closed gate template: `fairness_engine.py:183-195`, `compliance.py:80-93`.
**Verification**: an HCM/PII skill with **no** opt-in flag still triggers the fairness gate; test asserts the `FairnessAuditLog` row exists.

### 2D — Real audit gate + provenance integrity (D7, D8)
- Gate 6 (`enforce_audit_requirements`, `compliance.py:97-106`) must assert an actual ledger/provenance record was **persisted** for the action, not just that two booleans are truthy. Query the `quantum_ledger` for the execution's entry.
- Re-key the hash chain from **global timestamp** ordering (`quantum_ledger.py:48-53`) to **per-tenant monotonic sequence** to remove cross-tenant linearization fragility.
- Add a **scheduled** `verify_chain_integrity` sweep (`provenance.py:87`) to `scheduler.py` (join the existing `decay_checks`/`retention_sweep` jobs, `scheduler.py:94`).
**Verification**: Gate 6 fails an action whose ledger entry is missing; integrity sweep runs on schedule and reports per-tenant chain status.

### 2E — Fail-closed PII + erasure coverage (D9, D10)
- Under `DATA_RESIDENCY`/regulated posture, a scrub error must **fail closed** (block the cloud call), not degrade to unscrubbed (`llm_router.py:545,595`). Keep fail-open only in dev.
- Extend erasure (`privacy_erasure.py:11-22`) to purge **vector embeddings** (via `get_vector_store()` delete-by-subject) at minimum; document blob/backup erasure as an operational runbook step with a tracked ticket.
**Verification**: forced scrub failure with `DATA_RESIDENCY=true` raises instead of sending; erasing a subject removes their vector rows (queryable check).

---

## Phase 3 — Durable, Scalable Execution
> **Goal**: Make autonomy survivable and horizontally scalable — the prerequisite for automating the Foundry loop.

### 3A — Durable job queue (D11)
- Replace fire-and-forget `asyncio.create_task(_run_deployment_pipeline(...))` (`studio.py:30`) with a **persistent queue** (recommend **Arq** — async-native, Redis-backed, minimal footprint; Celery if the team prefers ecosystem breadth). Jobs get: durability, retry with backoff, idempotency keys, crash recovery.
- Gate job execution behind the existing `leader_lock` abstraction (`services/leader_lock.py`) so a POST landing on any worker enqueues, and a single elected runner drains — killing the "two concurrent POSTs run twice" footgun.
**Verification**: kill the worker mid-deployment; the job resumes/retries and the deployment row reaches a terminal state (not stuck).
**Anti-pattern guard**: no new `asyncio.create_task` for durable work.

### 3B — Horizontal readiness (D12)
- Move the in-memory rate limiter (`main.py:294-296`) to Redis (shared across workers/replicas).
- Ship a **k8s/Helm** baseline (or, minimum bar: the single parameterized compose from 1C + documented replica story) with readiness/liveness probes wired (`main.py:383-421` already exposes them) and the leader-gated singleton loops (`main.py:184-217`) proven safe at N replicas.
**Verification**: 3-replica run — rate limit is global not 3×; only one replica runs scheduler/PreCog/event-bus.

### 3C — Secrets & key hygiene (D13)
- Introduce a secrets backend (Vault / SOPS / cloud secrets manager); remove plaintext defaults from compose.
- **Decouple** `SECRET_KEY`: separate the JWT signing key from the connector/BYOK at-rest encryption key (`.env.example:11-13`); add a rotation mechanism so JWT rotation doesn't invalidate stored connector credentials (`RUNBOOK.md:119-120`).
**Verification**: rotate JWT key → existing connector creds still decrypt; secrets no longer present in any committed file.

### 3D — Observability on by default (D14)
- Expose `/metrics` by default behind a network ACL (fix `config.py:41` default + the compose scrape 404); ship the **OTLP exporter** package so `telemetry.py:26-30` actually exports; provision Grafana dashboards + Prometheus alert rules (empty today); wire Sentry (DSN placeholder `.env.example:98`).
**Verification**: `prometheus.yml` scrape returns 200; a trace reaches the OTLP collector; a dashboard renders safe-autonomy-rate (feeds Phase 5).

### 3E — CI → CD + supply-chain (D15)
- Add a CD stage: build, tag, **scan** (Trivy + SBOM), push image; environment promotion.
- Make `security-scan` **blocking** once the current backlog clears (`ci.yml:132-147`); SHA-pin GitHub Actions; ship **Python 3.12** to match CI (`Dockerfile:1` → 3.12); add the frontend test gate (Phase 6C).
**Verification**: a known-CVE base image fails the pipeline; released image digest is scanned and signed.

---

## Phase 4 — AI Foundry Closed Loop  ◄── **THE HEADLINE** (D16)
> **Goal**: Make "manufacture and continuously improve models" real, end-to-end, under human gate — without a single line of dishonest simulation. The eval/promotion half already exists; we build the trainer, the automation, and re-wire the orphaned catalog.

### 4A — Wire the orphaned catalog onto the hot path
- `ModelManagementService.route_to_model` (A/B canary, `model_management.py:139-151`) and `get_prompt` (versioned prompts, `:214-259`) are **real code with no runtime caller**. Make `LLMRouter.complete()` (`llm_router.py:317`) consult them instead of the hardcoded `MODEL_TIERS` dict (`:114`) and `skill_executor._EXEC_SYSTEM_PROMPT` (`:31`). This instantly makes canary routing and prompt versioning live.
**Verification**: a registered canary receives ~10% of tenant-hashed traffic on the real dispatch path; prompt version changes take effect without a deploy.

### 4B — Unify tier taxonomy
- Reconcile the router's 3 text tiers (`reasoning/classification/fast`, `llm_router.py:114`) with the registry's 4 (`FAST/STANDARD/DEEP/VERTICAL`, `infrastructure.py:24-28`). **`VERTICAL` becomes the home of a manufactured/fine-tuned domain model** — nothing routes there today.
**Verification**: routing a `VERTICAL`-tier skill dispatches to the promoted domain model.

### 4C — Pluggable trainer (`FineTuneProvider`)
- `dataset_builder.export_examples()` (`dataset_builder.py:283`) already emits fine-tune-ready JSONL. Add a **pluggable** `FineTuneProvider` interface: `submit(jsonl) → job_id`, `poll(job_id) → status`, `result(job_id) → candidate_model_id`. The candidate id flows straight into the existing `run_evaluation(candidate_model=...)` (`model_evolution.py:124`).
- Keep it **external/pluggable** (OpenAI/Together/local axolotl adapters) to preserve the honesty stance (`model_evolution.py:18-21`) — no in-repo fake trainer.
**Verification**: a real fine-tune job (or a local adapter) produces a candidate that runs through `run_evaluation`; a `simulated` result still cannot win/promote (`model_evolution.py:205,250`).

### 4D — Automate the loop ("continuously")
- Add scheduler jobs (`scheduler.py:94`): (1) `mine_executions` on a cadence, (2) a candidate→eval trigger when the mined dataset crosses a size/quality threshold. **Promotion stays human-gated** (`api/routes/foundry.py:198-223`) — automation feeds the funnel, humans still pull the lever.
**Verification**: with automation on, new governed executions accumulate → a candidate is proposed → it sits in the admin promote queue; no auto-promotion occurs.

### 4E — Multi-objective eval
- Extend `score_text` (token-F1 only, `model_evolution.py:54-75`) into a multi-objective score: add the `model_probe` dimensions (JSON/instruction/reasoning, `model_probe.py:63-99`) + **cost** (from `CostEvent`) + **latency** + a **safety** dimension (gate-pass rate). "Improve" becomes multi-objective, not just F1.
**Verification**: a candidate that's more accurate but 5× costlier or lower gate-pass does **not** win.

**Copy-oriented anchors for Phase 4**: gated-promotion shape `model_evolution.py:236-284`; deterministic scoring `:54-75`; per-call cost `llm_router.py:455-496`; audit-logged admin action `api/routes/foundry.py:198-223`.

---

## Phase 5 — Safe-Autonomy-Rate as a First-Class Metric
> **Goal**: Turn the north star into an instrumented number — the platform's control loop and the enterprise sales artifact.

**What to implement:**
1. Define **safe-autonomy-rate** precisely: `(actions executed autonomously AND passing all gates AND with no post-hoc reversal/incident) / (total agent actions)`, computed from existing signals — gate outcomes (`runtime.py` `_emit_gate`), `SkillExecution` status, HITL routing (`hitl_manager`), and `CostEvent`.
2. Materialize a time-series (per-tenant, per-domain, per-skill) with a scheduled rollup job (`scheduler.py`).
3. Surface it: an executive number + trend + drill-down into *why* actions fell out of autonomy (which gate, which skill). Alert on regressions (Phase 3D alerting).
**Verification**: the metric reconciles against raw `SkillExecution`/gate logs for a known window; dashboard renders per-tenant; a synthetic gate-block moves the number.
**Anti-pattern guard**: the metric is **derived from real logged outcomes**, never estimated or seeded (echoes the `/billing` seeded-fiction lesson, `llm_router.py:399-401`).

---

## Phase 6 — Frontend v2 (surface the platform; fix the weakest layer) (D17)
> **Goal**: The new capabilities (Foundry console, Safe-Autonomy dashboard) need a UI, and the frontend is the least mature layer. Preserve its one real strength — **zero mock-data discipline** (`api/client.ts:2`).

- **6A — Server-state library**: adopt **TanStack Query** (or standardize on the already-built-but-unused `hooks/useApi.ts` — currently used in only 2 of 68 consumers). Kill the 50+ hand-rolled `useState`+`useEffect`+`try/catch` fetch blocks (e.g. `FinanceView.tsx` has 12; anti-pattern sample `RealityExperience.tsx:38-68`). Gets caching, dedup, invalidation, retry for free.
- **6B — OpenAPI type codegen**: generate types from the FastAPI schema; delete hand-written drift and the whole-domain `request<any>` calls (`client.ts:1029-1108`).
- **6C — Test infrastructure**: Vitest + React Testing Library + a Playwright smoke suite; add a `test` script (none today, `package.json:13-18`) and a CI gate (feeds Phase 3E).
- **6D — Client resilience**: add timeout/`AbortController`, retry/backoff, unmount cancellation; replace `window.location.reload()` 401 handling (`client.ts:29-35`) with a router redirect + refresh-token flow; move the token off `localStorage`; fix the WS **JWT-in-query-string leak** (`client.ts:1221-1229`).
- **6E — Decompose the monolith**: split the 775-line `App.tsx` into config-driven routes; add per-module error boundaries (only 1 exists today, `App.tsx:630`); decompose the 400–675-line views; systematic a11y pass (~20 aria/role usages app-wide).
- **6F — New v2 surfaces**: **AI Foundry console** (dataset → train → eval → promote queue) and the **Safe-Autonomy dashboard** (Phase 5).
**Copy-oriented anchors**: best-in-repo hook `hooks/useApi.ts:50-176`; reference consumer `pages/ExecutiveCockpit.tsx`; boundary `components/ErrorBoundary.tsx:18-68`.
**Verification**: `npm run test` green in CI; zero `request<any>` in `client.ts`; Lighthouse a11y ≥ 90 on core views; a killed request cancels cleanly on unmount.

---

## Phase 7 — Verification & Release
1. **Governance regression**: full gate suite (`test_gate3_byok_ceiling`, `test_pii_egress`, `test_tenant_isolation_search`, `test_28_cross_tenant_denial`, `test_retention_and_erasure`) + new Phase 2 tests (default-deny census, approver-integrity, structural-gate, real-audit).
2. **Migration**: forward/back on Postgres; drift gate; RLS-effective assertion on the new prod compose.
3. **Foundry closed-loop e2e**: mine → (real) train → eval → gated-promote, with simulated-guard proven to block.
4. **Full-fidelity e2e** with real Ollama (currently a manual pre-release step, `ci.yml:46-48`) — promote to a release gate.
5. **Load/chaos**: kill a worker mid-job (durable-queue recovery); 3-replica leader-singleton + shared rate-limit.
6. **Security review**: `/security-review` on the branch; make `security-scan` blocking; image scanned + signed.
7. Update `CODEBASE_MAP.md`, `CHANGELOG.md`, `SECURITY.md` advisory ledger; cut **v2.0.0**.

---

## Sequencing, effort & the one decision for the founder

**Recommended execution order** = phase order (1→7); Phases 4/5/6 can partially parallelize once Phases 1–3 land, because they depend on the hardened substrate but not heavily on each other.

**Rough effort weighting** (relative, not calendar): Phase 1 (S), Phase 2 (M), Phase 3 (L), Phase 4 (M-L, headline), Phase 5 (S-M), Phase 6 (L), Phase 7 (M).

**The single strategic fork** worth an explicit founder call — it changes only *emphasis/order*, not the plan:
- **(A) Enterprise-sale-first** → front-load Phases 1–3 + 5 (a defensible safe-autonomy story sells; Foundry follows).
- **(B) Capability-leap-first** → pull Phase 4 forward right after Phase 2 (headline demo sooner; harden ops in parallel).
- **(C) Debt-paydown-first** → Phases 1, 6, and 3E before new capability (max stability).

The plan as written is **(A)-leaning**, because safe-autonomy-rate is the north star and the substrate gaps (D3, D5, D7, D11) are the kind that turn into incidents the moment autonomy scales. Redirect and the phase weights shift accordingly.
