# Changelog

All notable changes to KAEOS are documented here. This project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased] - v2.0 "Self-Improving Autonomy Platform" (in progress)

Executing the phased v2.0 upgrade in [docs/V2_MAJOR_UPGRADE_PLAN.md](docs/V2_MAJOR_UPGRADE_PLAN.md).
Thesis: harden the safety and ops substrate first (earn the right), then ship the
AI Foundry closed loop; the north-star metric is safe-autonomy-rate.

### Added
- **Frontend test harness (Phase 6).** The frontend had zero tests; added Vitest
  + jsdom + React Testing Library with a `test` script, a shared setup, and the
  first suites (pure-util `toPct` + an `ErrorBoundary` render test). Wired
  `npm test` into the CI `frontend-build` job so it gates merges. (The broader
  frontend v2 work - server-state library, OpenAPI codegen, resilience - builds
  on this harness.)
- **Deployment crash recovery (Phase 3).** A leader-guarded scheduler job
  (`run_deployment_reaper`, every 15m) transitions deployments left stuck in a
  non-terminal state by a crashed/restarted worker to FAILED (with a recoverable
  error-log entry), so the fire-and-forget pipeline no longer hangs a deployment
  forever. (Full durable-queue execution remains a follow-up.)
- **AI Foundry continuous mining (Phase 4D).** A leader-guarded scheduler job
  (`run_foundry_mining`, every 6h) curates every tenant's governed executions into
  training examples on a cadence, so the improvement loop runs continuously instead
  of only on a manual API call. Idempotent (already-mined executions are skipped);
  model promotion stays human-gated.
- **Safe-autonomy-rate as a first-class metric (Phase 5).** New
  `GET /metrics/safe-autonomy` computes the north-star metric live from logged
  executions: the rate, an explainable fallout breakdown (routed-to-human,
  overridden, edited, failed), a per-skill split showing where autonomy leaks,
  and a daily time-series. Derived from real `skill_executions` rows, never seeded.
- **Always-on KAEOS Copilot.** A persistent bottom-right chat dock on every screen
  so any authenticated user can ask questions in natural language. Rewrote the
  copilot to send real Bearer auth (it previously sent none), fixed broken SSE
  stream parsing, and made it reachable by all roles (read-only Q&A). Verified
  end-to-end (login to streamed answer).
- **Router-level default-deny** for state-changing routes, with an enforcement
  test (`tests/test_default_deny.py`) that fails CI on any new ungated mutation.
- Real Alembic migration `0006_state_snapshots_append_only` (first migration
  authored with `op` DDL rather than `create_all`).
- New regression suites: graph consolidation, append-only state, deploy RLS
  safety, HITL approver integrity, PII egress fail-closed.

### Changed (Phase 1 - Foundation Discipline)
- `init_db` gates `create_all` to dev/test; production schema now comes from
  Alembic. Registered `enterprise_state`/`enterprise_graph`/`intelligence_metrics`
  (27 tables) that were missing from the bootstrap, so the migration baseline is
  now complete (216 tables). Made `enterprise_graph` JSONB portable to SQLite.
- Enterprise State is now append-only (each mutation writes a new snapshot;
  dropped the UNIQUE `tenant_id` index that forced in-place overwrite).
- Deleted the fake in-memory "Neo4j" graph provider; `GraphService` now delegates
  to the real polystore graph store, and `FitnessCalculator` / `ScorecardEngine`
  compute from the real graph instead of returning fixtures.

### Changed (Phase 2 - Safety Hardening)
- HITL approvals record the authenticated principal, not a client-supplied
  (spoofable) approver name; unified into one `approver_identity` helper.
- PII egress scrubbing fails closed under a data-residency policy
  (`DATA_RESIDENCY` / `SCRUB_PII_BEFORE_LLM`) instead of degrading to unscrubbed.
- Fairness-gate applicability is now STRUCTURAL: a people-affecting (HCM /
  protected-class) decision is assessed based on the skill's department, id,
  tags, and affected-entity type, so it can no longer skip the gate by omitting
  the `requires_fairness_assessment` flag (the flag still works as an override).
- Post-execution audit gate (Gate 6) now requires the actual audited datum, not
  just a "logged" flag: SOX needs the financial amount, GDPR/HIPAA/CCPA need a
  lawful basis. A flag without the underlying value no longer passes.
- GDPR erasure now purges the subject's embeddings from the vector store
  (`VectorStore.delete_subject`), closing the vector-layer coverage gap.

### Changed (frontend de-duplication)
- Removed duplicate pages/tabs identified by a data-source audit (same `api.*`
  fingerprint = same functionality): **Analyst Workspace** (its graph belongs to
  Topology; its audit log was the same `getGlobalLedger()` as Provenance Ledger),
  the **Agent Fleet** tab (same `getSkills`+`getExecutions` as the Knowledge
  "Skill Builder"), and the connector triplication (**Connector Studio** +
  **System Connections** tabs both managed connectors already owned by the
  top-level `/integrations` page). Deleted `AnalystWorkspace`, `AgentMonitor`,
  `IntegrationsHub`, and the dead-mock `ExecutiveAdvisor`. Renamed the "Skill
  Marketplace" tab to "Skill Templates" to end the collision with the
  `/marketplace` domain-pack page. See docs/NAV_AND_MOCKDATA_PLAN.md.

### Added (v4 Signature IP)
- **Shock simulator upgrade: Scenario Comparison** (IP-2) — each shock run is now
  captured and ranked side-by-side by severity, with blast (impacted node count),
  a severity bar, and the executed decision, so single shocks become scenario
  planning. Real data (each run is a `/reality/shock` call), in Reality Experience
  (no new nav). Verified live: Cyber Incident → HR (sev 95) ranked above Employee
  Termination (sev 60).
- **What-If Scenario Simulator** (IP-1) — a second mode beside the Shock simulator
  in **Reality Experience** (no new nav). Propose a change in plain language and get
  a governed verdict (SAFE/RISKY/BLOCKED), a **real blast radius** computed from the
  tenant's data (executable rules + skills + departments actually in scope — not
  hallucinated), a rollback-time estimate, and (when the LLM is available) ranked
  risk factors with mitigations + a recommendation. Surfaces the previously-orphaned
  real `/simulation/what-if` endpoint, upgraded to compute the blast radius from the
  DB so it is meaningful even without a cloud model. Verified live end-to-end.

### Added (v3 — Cross-Domain Autonomous Missions, Phase 3)
- **Autonomy that PURSUES goals.** A plain-language goal ("close the quarter: review
  the vendor contract, approve the budget, brief support") is decomposed into a
  governed DAG of steps, each **grounded in a real ACTIVE skill** across departments
  (canonical department aliasing so `human_resources`/`customer_support` match), with
  a real LLM (local qwen) narrative explaining the plan. New `missions` +
  `mission_steps` + `mission_events` tables (migration 0010, RLS). Service:
  `services/missions/` (planner + engine). API: `POST /missions` (plan),
  `/{id}/advance`, `/{id}/steps/{seq}/hitl`, `/{id}/abort`, plus list/detail.
- **Governed, one-step-at-a-time execution.** Each step runs as a governed advisory
  action through the full 7-gate `AgentExecutor` (a mission is goal-level
  orchestration/planning; transactional compliance + write-back stay in Phase 1 with
  real entity data). Per-department HITL from the real Autonomy Dial policy, a budget
  gate, a mission ledger, and honest exception handling: a compliance block on an
  autonomous step **escalates to a human**, a failed step is flagged as an exception
  (not a mission-wide crash), and independent steps keep progressing. Abort reverses
  any actuations the mission caused (Phase 1 compensators).
- **Mission Control UI** in the Agents view (a tab beside Agent Deployment, no new
  nav): launch a goal, watch the plan DAG with per-step department/confidence/HITL
  status, approve/reject checkpoints inline, a budget meter, and the live mission
  ledger. Verified end-to-end on the real qwen model: a 2-department mission planned,
  ran sales autonomously, paused support for approval, and completed with real
  model-authored recommendations. Tested (9 orchestration tests: plan grounding,
  budget gate, HITL approve/reject, compliance escalation, failure-as-exception,
  abort).
- **Run on real models by default.** Confirmed the LLM router uses the local Ollama
  `qwen2.5-coder:7b` for every gate whenever Ollama is reachable (simulated output is
  only a fail-closed fallback); the dev backend now runs without `ALLOW_SIMULATED_LLM`
  so governance decisions are made by the real model.

### Improved
- **Executive Cockpit layout.** The Agent Consciousness Stream, Pioneer Intelligence,
  and Cost & ROI cards now fill their row evenly (a capped feed height left dead
  space). The **Cost & ROI Tracker** gained live metrics: 24h token + LLM-call volume,
  a per-model-tier breakdown (reasoning/fast/classification tokens · calls) from real
  telemetry, and the budget ring — all real, with honest $0 cost for local models.

### Added (v3 — System-of-Record Actuation, Phase 1)
- **Autonomy that DOES: governed, idempotent, reversible write-back.** New
  `services/actuation/` Actuator applies a mutation to a real backing
  system-of-record row (`sor_objects`), keyed by a deterministic idempotency key
  (a retry is a no-op that returns the original record, never a duplicate write),
  captures before/after state, registers a compensator (the exact inverse), and
  appends to the provenance hash-chain. New `action_records` table + `sor_objects`
  (migration 0009, RLS on both). API: `POST /actuation/execute` (operator-gated),
  `POST /actuation/{id}/reverse`, `GET /actuation/ledger`, `GET /actuation/drift`.
  Wired into the agent runtime as **Gate 5b** — a skill may declare an `actuation`
  intent and the write-back only fires *after* the compliance / fairness /
  confidence-HITL / debate gates pass, inheriting full governance (non-fatal: a
  failed write is recorded, not raised). Tested (create/update/delete, idempotent
  retry, reverse restores prior state, drift detection, reversal-is-not-drift).
- **Actions Ledger (UI).** A new tab in **Decisions** beside the Provenance
  ledger — what KAEOS *did* to a system of record (governed and reversible),
  distinct from the *decision* ledger. Status summary (applied/reversed/failed), a
  reconciliation banner (records in sync vs drifted outside the governed path), and
  a one-click Reverse on any applied action. Verified live end-to-end: three real
  governed writes recorded, a reversal restored prior state, drift stayed at zero.

### Fixed
- **Fairness Audit Log score showed "-".** The Trust & Governance fairness log read
  a non-existent `composite_score` field; the API returns `fairness_score`. Now
  shows the real score vs threshold, a PASSED/BLOCKED chip, and the rationale
  (the data was always live — only the display field was wrong).
- **Analytics "Live" badge overlapped the KPI cards.** A negative margin pulled the
  KPI grid up under the badge in every domain analytics view; removed it so the
  live-sync indicator keeps clear separation above the cards.

### Added (v3 — Outcome Intelligence Loop, Phase 2)
- **Decision → outcome learning loop.** Record a measured real-world outcome for a
  past decision (`POST /outcomes/{execution_id}`, GOOD/BAD/NEUTRAL) and it feeds
  back into the executing skill's confidence (GOOD +0.02, BAD -0.05) — so the
  system learns from reality, not only from human labels at decision time.
  `GET /outcomes/impact` aggregates the distribution, autonomous-vs-human decision
  quality, and per-skill outcome quality. New `outcome_records` table
  (migration 0008, RLS). Tested (confidence feedback + impact split).
- **Outcome Intelligence panel (UI).** The loop is now closed in the product:
  Decisions → Feedback & Evolution gains an Outcome Intelligence panel that shows
  the live good/neutral/bad distribution and the autonomous-vs-human good-rate
  split (from `GET /outcomes/impact`), plus a recorder that lists recent HITL
  decisions and lets an operator mark each GOOD/NEUTRAL/BAD in one click; the mark
  posts the outcome and refreshes the impact in place. No new nav (extends the
  existing Feedback & Evolution surface). Verified end-to-end in the browser
  (recording a mark moves the distribution and the human good-rate live). Also
  fixed a pre-existing NaN in the evolution timeline when the KB score trend is
  non-numeric ("held steady" instead of "declined NaN%").

### Added (v3 — Autonomy Dial, Phase 7)
- **The Autonomy Dial** — executives set a per-department risk appetite (the
  confidence a decision must clear to run without a human) in **Settings → Platform**
  (no new nav). It has real teeth: Gate 3 in the agent runtime reads the per-domain
  threshold (`resolve_min_confidence`, cached) and falls back to the platform default
  when unset; high-consequence actions still always require a human. New
  `autonomy_policies` table (migration 0007, RLS), `GET/PUT /config/autonomy`
  (admin-gated write), and a slider UI. Tested + verified live (drag Finance to 72%
  → persisted, gate enforces it).

### Added (v3 UI)
- **Autonomy fallout breakdown, folded into the Dashboard** (not a separate page).
  The Dashboard already owns the safe-autonomy rate + trend + earned-autonomy; the
  one genuinely new insight from `GET /metrics/safe-autonomy` — *why* work fell out
  of autonomy (routed-to-human / overridden / edited / failed) — is now a row on the
  Dashboard. No duplicate navigation touchpoint. All real, no mock.

### Added (planning)
- **docs/KAEOS_VISION_PLAN.md** — the v3 "Autonomous Enterprise" plan: new,
  non-duplicative layers (system-of-record actuation, outcome-intelligence loop,
  cross-domain autonomous missions, enterprise flight simulator, sense-decide-act
  event mesh, regulatory autopilot, trust/autonomy-dial, omnipresent touchpoints).

### Fixed
- **Workforce Analytics showed 0% automation and 0 active agents** despite 140
  real executions and departments reporting 6/7/5 agents. `agents_active` counted
  an empty detail table instead of the denormalized `agent_count` sum; automation
  averaged an unpopulated `Department.automation_coverage` column. Both now compute
  from real data (agent_count sum; autonomous/total executions, per-department via
  a skill-department join with slug normalization) — the headline is ~86%, not 0%.

### Fixed (security-critical)
- `backend/docker-compose.prod.yml` connected the app as the DB **owner**, which
  silently disables row-level security (owners bypass RLS). It now connects as the
  non-owner `kaeos_app` role with a separate owner URL for migrations; the prod
  entrypoint runs migrations under the owner URL. Added a guard test.

## [1.1.2] — 2026-07-21

Security hardening release. Closes a Host-header auth-bypass vector surfaced by
the Starlette advisory review in 1.1.1, and records the disposition of every
open Starlette advisory. No functional changes to features.

### Security
- **Fixed auth-bypass (GHSA-86qp-5c8j-p5mr, in-code mitigation).** Starlette
  `<1.0.1` rebuilds `request.url` from the attacker-controlled `Host` header, so
  a malformed `Host: victim/health?x=` made `request.url.path` read `/health`
  (a public path) while the router still dispatched the real **protected** route
  from `scope["path"]` — skipping the token check and assigning the dev tenant.
  The upstream fix ships only in Starlette 1.0.1 (unreachable — no FastAPI
  supports 1.x), so KAEOS's security gates now key off the raw ASGI
  `scope["path"]` instead of `request.url.path`:
  - `app/core/tenant.py` — the tenant/auth public-path gate.
  - `app/core/middleware.py` — the rate-limit exemption and request-log path.
  - Regression test: `tests/test_tenant_middleware.py::test_poisoned_host_header_cannot_bypass_auth_gate`.
- **Advisory disposition table** added to [SECURITY.md](SECURITY.md) covering all
  six Starlette advisories: 2 fixed by upgrade (1.1.1), 1 mitigated in code
  (86qp), 2 not-applicable and dismissed (x746 — no `HTTPEndpoint`; wqp7 — no
  `StaticFiles`/Linux), 1 accepted/tracked (82w8 — ingress-mitigated DoS).

### Fixed
- **Frontend lockfile drift** — `frontend/package-lock.json` referenced
  `react@19.2.8` while pinning `react@19.2.5`, breaking `npm ci` (`frontend-build`
  CI job). Re-pinned `react` + `react-dom` to `19.2.8` in lockstep so the lock is
  consistent with `package.json`.

## [1.1.1] — 2026-07-21

Maintenance & dependency-security release. Fixes the CI dependency-resolution
break introduced around 1.1.0 and patches upstream Starlette advisories, with no
functional changes to the platform.

### Security
- **Starlette `0.38.6` → `0.48.0`** (via **FastAPI `0.115.0` → `0.119.1`**),
  clearing two upstream advisories:
  - **GHSA-f96h-pmfr-66vw** (HIGH) — DoS via `multipart/form-data` (fixed 0.40.0).
  - **GHSA-2c2j-9gv5-cj73** (MEDIUM) — DoS parsing large multipart files (fixed 0.47.2).
- **GHSA-wqp7-x3pw-xc5r** (HIGH, StaticFiles SSRF/NTLM on Windows) — **not
  applicable**: KAEOS serves no `StaticFiles` and deploys on Linux
  (`python:3.11-slim`). Alert dismissed with rationale.
- **GHSA-82w8-qh3p-5jfq** (HIGH, form-urlencoded DoS) — **accepted / tracked**:
  only patched in Starlette 1.3.1, which no released FastAPI supports and which
  breaks `require_role` routing. Mitigated at ingress (reverse-proxy body-size
  limit). See [SECURITY.md](SECURITY.md).

### Fixed
- **CI dependency resolution** — the previous `starlette==1.3.1` pin was
  un-installable against FastAPI (`starlette<0.39.0` required), failing
  `backend-test` and `backend-e2e-mock`. Now resolves on a supported combo.

### Changed
- Added **`.github/dependabot.yml`** — grouped, weekly updates for pip / npm /
  github-actions, with Starlette `>=1.0.0` ignored (FastAPI-incompatible; see
  SECURITY.md) so the impossible security bump stops recurring.

## [1.1.0] — 2026-07-21

The **Workflow, Analytics & Collaboration Platform** release. Turns the seven
department brains from read-only dashboards into an operational system: every
core entity now has a guarded lifecycle, live cross-domain analytics, ownership,
comments, automation, and a unified notification surface — all on real tenant data.

### Added
- **Shared workflow engine** (`app/core/workflow.py`) — declarative per-domain
  state machines with guarded transitions, per-target-state **role floors**,
  business **guard** callables, **SLA thresholds**, a `core_workflow_events`
  audit trail, and a tenant WebSocket broadcast on every transition. Illegal
  moves return 409 with the allowed set; foreign-tenant rows 404 (never confirm ids).
- **Per-domain analytics + workflow endpoints** across Finance, HR, Sales,
  Support, Operations, Legal, Engineering — `GET /{domain}/analytics` (live SQL
  KPIs, charts, insights), `/{domain}/workflows`, `/{domain}/workflow-events`,
  guarded `POST .../{id}/transition`, `POST .../workflows/{type}/bulk-transition`
  (per-id outcomes), and validated entity-**creation** endpoints with auto-numbering.
- **Org Pulse** (`/pulse`) — cross-domain health (insight-severity + SLA-breach
  weighted), unified needs-attention feed, live workflow activity, an **SLA
  Breaches** table, and one-click **Escalate all** (idempotent alerting).
- **Assignment & My Work** (`/my-work`) — assign any entity, per-user "my work",
  team workload, all cross-domain.
- **Comments & @mentions** on any workflow entity, with mention notifications.
- **Automation rules** (`/automation`) — declarative "when an entity dwells in a
  state past N hours, transition / assign / escalate"; rules validated against the
  live workflow registry, evaluated on demand.
- **Notifications & digest** — unified notification feed with unread counts,
  mark-read, and a one-call org digest; SLA/mention/automation alerts surface in
  the header bell alongside the HITL queue.
- **CSV export & saved segments** — export any workflow entity type; save named
  per-domain filters.
- **Live-feel UI** — a `LiveBadge` (WebSocket heartbeat + "synced Ns ago") on the
  main dashboards; domain views and analytics auto-refresh on tenant events.
- Alembic `0004_workflow` and `0005_workspace` (RLS-guarded on Postgres).

### Changed
- **Departments → Marketplace → Deploy** unified into one funnel: Departments
  shows what you run, the Marketplace is the catalog, and "Deploy This Pack"
  carries the chosen pack into the wizard (skipping its duplicate pack-picker).
  Standalone "Deploy" removed from the top nav.
- **ROI cost-saved** now derives transparently from live hours-saved × a
  documented loaded hourly rate (`LOADED_HOURLY_RATE_USD`, default $85) instead of
  reading an unpopulated metrics table — fixes the `$0` cost card while hours were
  non-zero. Rate is shown as a footnote for honesty.

### Fixed
- SLA-escalation dedupe now matches the `action_taken` column's `False` default
  (not just NULL), so re-running escalation never re-alerts open breaches.

## [1.0.0] — 2026-07-20

First public release.

### Added
- **Company Brain** — unified rules/skills/signals layer with a cross-domain
  knowledge graph and 5-dimensional confidence scoring.
- **Seven Department Brains** — HR, Finance, Legal, Sales, Support, Operations,
  and Engineering & IT Ops, each with domain agents running the gated pipeline.
- **Agent Factory** — create → approve → compile → deploy → orchestrate agents
  from a plain-English prompt.
- **Governance spine** — compliance / fairness / confidence-HITL / adversarial-debate
  gates, a hash-chained (tamper-evident) provenance ledger, and red-team checks. Gates **fail closed**.
- **AI Foundry (Phase 2)** — curates execution history into a tenant-scoped,
  RLS-isolated training dataset. (Model fine-tuning is a later phase and is
  labelled as such in-product — no models are trained today.)
- **Real-data benchmarks** — decision logic scored against seven public enterprise
  datasets; wins **and** losses reported transparently (`backend/benchmark`).
- **BYOK LLM routing** — LiteLLM gateway across Anthropic/OpenAI/Groq/Ollama with
  retry, circuit-breaker, budget gate, and per-call cost metering.

### Security
- Per-tenant **PostgreSQL Row-Level Security** on every tenant table, verified
  effective at startup (`assert_rls_effective`) and provable via `scripts/verify_rls.py`.
- No default/public login — the root admin is provisioned from `ADMIN_EMAIL` /
  `ADMIN_PASSWORD`; nothing ships with known credentials.
- **JWT sessions via PyJWT** (migrated off `python-jose` to close the algorithm-
  confusion CVE) with per-token `jti`, a revocation denylist, and a `/auth/logout`
  that revokes the caller's token. Login has brute-force lockout after repeated
  failures and a minimum password length on user creation.
- **Role-based access control** (`viewer`/`operator`/`admin`) enforced via
  `require_role` on consequential/mutating endpoints (create, update, delete,
  execute, HITL approve, connector credentials, deployment, pack install); cross-
  tenant platform actions gated on an admin secret. HITL approvals are role-gated
  and recorded against the authenticated principal, not free text.
- **High-consequence actions always route to a human.** Payments, terminations,
  contract execution, external sends, and data deletion force the HITL gate
  regardless of model confidence; the confidence threshold itself is configurable
  (`CONFIDENCE_AUTONOMOUS_EXEC`) rather than hardcoded.
- **Security audit trail** (`SecurityAuditLog`) wired to real runtime events —
  auth successes/failures, RBAC denials, HITL decisions, config/connector/export
  actions — as a best-effort writer that never blocks a request.
- **Data protection** — right-to-erasure (`privacy_erasure`), a `DATA_RESIDENCY`
  local-LLM-only mode that refuses cloud providers and strips cloud credentials,
  optional PII scrubbing before cloud egress, and PII redaction in logs.
- `/metrics` is **off by default** (opt-in via `EXPOSE_METRICS`); interactive API
  docs fail closed outside a development environment. The `python_sandbox` agent
  tool is off by default (prompt-injection RCE surface).
- BYOK connector credentials encrypted at rest (PBKDF2-derived key); hardened
  agent code sandbox; fail-fast production config validation (refuses to boot on
  insecure config or SQLite-in-production).

### Verified
- Full end-to-end suite (**426 tests**, 29 files) green on SQLite **and** on
  PostgreSQL + pgvector against a live server with a local LLM.
- Black-box attack re-checks against the running container: malformed login
  returns 422 (not 500), `/metrics` is hidden, liveness probe works, brute-force
  lockout engages, and unauthenticated HITL approval is rejected.
- Tenant isolation verified on real PostgreSQL: cross-tenant reads scoped,
  cross-tenant writes blocked, missing-context fails closed.
- Independent adversarial code review of the security remediation: no
  Critical/High regressions found.

### Known limitations / roadmap
- AI Foundry model **fine-tuning** (Phases 3–5) is not implemented yet.
- Some "frontier" simulation surfaces (enterprise-physics what-if, evolution
  fitness) are parameterized simulations, labelled as such — not learned models.
- Rate limiting is per-process (in-memory); use a shared limiter behind a
  multi-instance deployment.
- Pre-production checklist (load testing, a formal pen-test, and a one-time
  connector-credential re-encryption if upgrading) is in `docs/DEPLOYMENT.md`.
