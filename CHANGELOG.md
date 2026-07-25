# Changelog

All notable changes to KAEOS are documented here. This project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased] - v2.0 "Self-Improving Autonomy Platform" (in progress)

Executing the phased v2.0 upgrade in [docs/V2_MAJOR_UPGRADE_PLAN.md](docs/V2_MAJOR_UPGRADE_PLAN.md).
Thesis: harden the safety and ops substrate first (earn the right), then ship the
AI Foundry closed loop; the north-star metric is safe-autonomy-rate.

### Added (Self-improving autonomy — closed loops)
- **L7 Missions -> governed actuation.** Mission steps ran advisory-only
  (`tool:"none"`, no `actuation`), so runtime Gate 5b never fired and missions
  could only recommend. `MissionStep` now has an `actuation` column (migration
  `0016`); a HUMAN-APPROVED step carrying a concrete actuation intent hands it to
  the runtime so Gate 5b performs the idempotent, reversible write AFTER every
  gate passes — turning missions from "recommend" into governed "do". Advisory
  steps are unchanged. Tests: `tests/test_mission_actuation_l7.py`.
- **L1 Outcome -> execution learning.** Recording a measured outcome now stamps
  `SkillExecution.outcome_type`, so the AI Foundry (which mines SkillExecution,
  not OutcomeRecord) curates on real outcomes, not just on completion.
- **L4 Event-mesh -> outcome.** When an event-mesh-spawned mission finishes, its
  terminal status is written back to the originating `ExternalSignal` (-> RESOLVED)
  and an `OutcomeRecord` is recorded (GOOD/BAD), feeding the L1 loop. Idempotent
  and scoped to `created_by=="event-mesh"`. Tests: `tests/test_closed_loops_l1_l4.py`.

### Added (Production-readiness — audit export & user management)
- **CSV export for audit/compliance evidence (P1).** New `GET
  /actuation/ledger/export`, `GET /provenance/global/ledger/export`, and `GET
  /dashboard/compliance/export` return downloadable CSVs so operators can hand
  auditors the Actions Ledger, Provenance (decision) Ledger, and per-framework
  compliance status without screen-scraping. The provenance export is tenant-safe
  (inner-joined to the caller's own rules). Shared helper `core/csv_export.py`.
- **Invite-based user onboarding + reactivation (P1).** Admins no longer type a
  new user's plaintext password: `POST /auth/users/invite` creates an inactive
  account and returns a signed, 7-day magic-link token; the invitee sets their own
  password via the public `POST /auth/accept-invite`. Deactivated users can be
  restored with `POST /auth/users/{id}/reactivate` (tenant-scoped). Tests:
  `tests/test_user_invite_export.py`.
- **Fetch-error UI on the Executive Cockpit (P1).** The cockpit dropped
  `anyError`, so a backend outage rendered as "No data yet"; it now renders
  `BrainError` with a retry. (The same sweep across the other top pages —
  OrgPulse, FinanceView, MissionControl, the 7 domain views, UserManagement — plus
  the orphaned-capability UIs, DSAR/billing/webhooks, remain a tracked follow-up.)

### Changed (Production-readiness — reliability)
- **API keys moved to a DB-backed store (P1).** The key store was a module-global
  JSON dict loaded once at import, so a key generated or revoked in one gunicorn
  worker / replica was invisible to the others until a restart — runtime revocation
  did not actually take effect fleet-wide. Added an `api_keys` table (migration
  `0015`, RLS on Postgres, only the SHA-256 hash stored) and routed every lookup,
  generation, and revocation through it (`core/auth.py`, the tenant middleware, the
  WebSocket auth, and the admin issue/revoke endpoints). Revocation now propagates
  immediately across all workers/replicas. Tests: `tests/test_api_keys.py`.

### Fixed (Production-readiness — honesty & hardening)
- **Removed over-labeled confidence/coverage (P1).** Template workflows no longer
  ship a fabricated `coverage_score=0.85` (now `0.0` until real runs measure it);
  template rules downgrade from `0.88/VERIFIED` to `0.5/INFERRED` (matching sibling
  Skills); the regulatory engine's LLM-synthesized rule is `INFERRED` not `VERIFIED`
  (its `outcome_validation`/`explicit_validation` are 0.0), and its result status is
  `RULES_SYNTHESIZED` instead of the over-claiming `COMPLIANCE_ACHIEVED`.
- **Service-to-service auth for the agent mesh (P1).** The agent-mesh / cost /
  model-routing mutations (`/infrastructure/agents/*`, `/cost/check|record`,
  `/models/route`, `/schema-mappings/propose`) were reachable by ANY authenticated
  viewer. They now require `require_service_or_role("operator")` — a valid
  `X-Service-Token` (machine-to-machine) or an operator role — and are removed from
  the default-deny allowlist (the enforcement test now recognizes the gate).
- **Distributed rate limiting + body-size guard (P1).** The rate limiter was
  in-memory per-process (N× the intended limit under `-w4`); it now uses a shared
  Redis fixed-window counter when Redis is reachable, falling back to in-memory
  only single-instance. Added a `BodySizeLimitMiddleware` that rejects over-large
  request bodies (413) before a handler allocates them (OOM guard;
  `MAX_REQUEST_BODY_BYTES`, default 10 MiB). Tests: `tests/test_middleware_limits.py`.

### Added (Production-readiness — reliability)
- **Durable job queue (P0).** The deployment pipeline ran as fire-and-forget
  `asyncio.create_task`, so a worker restart mid-deploy lost the task entirely.
  Added a DB-backed at-least-once job queue (`jobs` table, migration `0014`, RLS
  on Postgres) that fits KAEOS's existing operational model (leader-elected
  APScheduler + owner-session sweeps) instead of adding a Celery/Redis broker.
  Jobs are persisted before execution; a leader-guarded processor
  (`run_job_queue`, every 15s) claims due jobs with a conditional `WHERE
  status='QUEUED'` update (so a lost-lease overlap can't double-run), dispatches
  to a registered handler, and retries with backoff up to `max_attempts` or marks
  FAILED. A stuck-job reaper (`run_job_queue_reaper`, every 5m) requeues jobs a
  dead worker left RUNNING (the at-least-once backstop). The deployment pipeline
  is the first handler (`deploy_pipeline`); the existing deployment reaper stays
  as a second backstop. Tests: `tests/test_job_queue.py` (7) cover success,
  no-handler, fail-without-retry, retry-with-backoff (no hot-loop), leader-guard
  no-op, and stuck-job recovery/exhaustion.

### Added (Production-readiness — enterprise auth)
- **Real OIDC single sign-on (P0).** Enterprise SSO was a 501 stub plus an
  in-tree mock middleware that accepted a literal `"mock_valid_jwt"` (an auth
  bypass primitive). Shipped a complete, real OpenID Connect Authorization Code
  flow (`app/services/sso.py`, `/auth/sso/oidc/authorize` + `/callback`): IdP
  discovery, `state`+`nonce` carried in a short-lived HMAC-signed token (stateless,
  multi-worker safe), authorization-code exchange over TLS, **RS256 id_token
  signature verification via the IdP's JWKS** plus issuer/audience/expiry/nonce
  checks (PyJWT), and just-in-time user provisioning that mints a normal KAEOS
  session (provisioned accounts get an unusable password hash — SSO-only, never
  password-loginable). Covers Azure AD, Okta, Google, and Auth0. Per-tenant IdP
  config lives in a new `sso_connections` table (migration `0013`, RLS on
  Postgres) with the **client secret Fernet-encrypted at rest and never returned
  by the API**; managed through an ADMIN-gated config surface
  (`/auth/sso/connections`). Deleted the mock middleware. SAML remains an honest
  501 that points callers to OIDC. Tests: `tests/test_sso.py` (13) cover signed
  state, secret encryption, real RS256 verification incl. nonce/audience
  rejection, JIT provisioning/reuse/deactivation, and the config surface.

### Fixed (Production-readiness — security)
- **Cross-tenant graph leak closed (P0).** The polystore graph store
  (`polystore_graph_nodes` / `_edges`) had no `tenant_id` column and no RLS, so
  `_load()` / `snapshot()` / traversals returned EVERY tenant's nodes and edges -
  a reachable cross-tenant path on any Postgres-without-Neo4j deployment (the
  live `SqliteGraphStore` backend). Every node/edge now carries a `tenant_id`,
  the node primary key is `(tenant_id, id)` so ids are unique per tenant, and
  every read/write/traversal is filtered by tenant. `tenant_id` threads through
  `GraphStore` -> `GraphService` -> the fitness/scorecard/impact/synthetic
  consumers. On Postgres the tables are additionally placed under row-level
  security as a backstop (the existing `ensure_rls_policies` sweep plus an
  immediate enable at lazy-create time). Pre-tenant tables are migrated by
  dropping-and-recreating tenant-scoped (the graph holds derived/regenerable
  structure; serving untenanted rows *was* the leak). Regression-tested with a
  dedicated tenant-isolation case incl. same-id-across-tenants
  (`tests/test_graph_consolidation.py`).

### Fixed (Production-readiness — honesty)
- **Compliance dashboard no longer fabricates compliance (P0).**
  `GET /dashboard/compliance` previously hardcoded `violations: 0` and stamped
  `last_audit` = today for every framework, so GDPR/SOX/HIPAA/PCI/CCPA/SOC2 always
  rendered COMPLIANT with a fake audit date. It now counts REAL unresolved
  `ComplianceViolation` rows plus framework-attributed governance blocks
  (BLOCKED_COMPLIANCE / FAILED_AUDIT / HUMAN_OVERRIDDEN executions), derives
  `last_audit` from the latest real violation, compliance report, or monitored
  control execution, and renders **UNKNOWN** (never auto-COMPLIANT) for a framework
  that has coverage but no monitoring signal. Cross-tenant isolation is enforced and
  regression-tested (`tests/test_compliance_dashboard.py`).

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

### Added (v3 — Regulatory & Risk Autopilot, Phase 6)
- **Continuous regulatory intelligence** on top of the compliance gate. New
  `services/regulatory.py` computes, from real skills and executions: a
  regulation→control map (which skills carry which framework tags), an
  **EU-AI-Act-style per-skill risk register** (HIGH / LIMITED / MINIMAL from
  autonomy + tags + high-consequence surface, with the obligations each tier
  implies), a live compliance monitor (blocks / audit fails / human overrides in
  window), and **audit evidence packs** assembled from the real provenance +
  actions ledgers and control executions. `GET /regulatory/overview` and
  `GET /regulatory/evidence/{framework}`. Tested (7 cases).
- **Compliance dashboard upgraded in place** (Decisions → Compliance, no new nav)
  into "Compliance & Regulatory Autopilot": risk-tier summary + live monitor, the
  Agent Risk Register table, and one-click evidence-pack generation per framework.
  Verified live: 3 HIGH / 4 LIMITED / 1 MINIMAL risk skills, and a SOX evidence
  pack assembled from 2 controls, 42 executions, 28 ledger entries, 3 actions.

### Fixed
- **Earned Autonomy count mismatch.** The Workforce dashboard summarized all
  graduated/earning skills (e.g. 7) but the list was capped at 3 each (showed 4).
  Removed the cap so the list matches the count.

### Added (v3 — Sense-Decide-Act Event Mesh, Phase 5)
- **The enterprise OODA loop.** External-world signals (regulatory / vendor /
  security / market / supply-chain / news) are ingested, **correlated against the
  real twin** (the canonical 7 departments + skill ids, alias-normalized), and turned
  into a governed response: an uncorrelated signal gets no action; a warning briefs
  the owning team (activity feed); a critical single-department signal routes to HITL;
  a critical multi-department signal **spawns a cross-domain mission**. New
  `external_signals` table (migration 0011, RLS), `services/event_mesh.py`, and
  `POST /signals/ingest` / `GET /signals` / `POST /{id}/respond`. Tested (5 cases:
  kind-prior + text correlation, uncorrelated→no-action, critical→HITL/MISSION,
  respond marks responded).
- **Signals & Responses stream** on Org Pulse (no new nav): a live feed of each
  signal with its matched twin entities and the governed response badge
  (BRIEFING/HITL/MISSION/none), plus an operator/connector ingest control. Verified
  live: a critical security signal correlated to engineering+finance and spawned a
  real mission; a regulatory signal briefed legal.

### Improved (performance — no reasoning/quality change)
- **Composite DB indexes** on the hot analytics read paths: `skill_executions
  (tenant_id, started_at)` and `cost_events (tenant_id, timestamp)` (migration 0012,
  idempotent). Every analytics endpoint (safe-autonomy, time-machine, causal,
  regulatory, cost telemetry) filters exactly on those; the query plan now uses a
  covering-index seek instead of a scan.
- **In-flight GET deduplication** in the frontend API client: concurrent identical
  reads (a page's mount fetch + a live-refresh tick + multiple components) share one
  request. Zero staleness (only collapses *concurrent* identical GETs), fewer calls.
- **Bounded debate generation**: the debate gate's LLM calls now cap `max_tokens`
  with ample headroom over the short JSON verdict — prevents a confused model from
  runaway generation without ever truncating a well-formed response.
- **Model strategy (researched, hardware-gated).** On the 6GB dev GPU the 7b cannot
  co-reside with a helper model (loading a 1.5b evicts the 7b), so tier-splitting to a
  lighter model would swap-thrash — verified and documented; nothing is routed to the
  lighter tier here. See docs/PERF_OPTIMIZATION_PLAN.md.
- **Async missions.** A gated mission step can take a while on a live model, so
  `POST /missions/{id}/advance` no longer blocks: it starts a background runner
  (own DB session, per-mission guard, stale-step crash recovery) and returns
  immediately; the UI polls `GET /missions/{id}` for live progress. Verified: advance
  returns in ~0.3s (was ~2 min), the runner executes steps server-side (sales
  RUNNING→DONE) and pauses at HITL. Same governance, same output — just non-blocking.
- **Per-model-tier latency measurement** surfaced in the Executive Cockpit (calls ·
  avg latency) from the existing CostEvent data — makes the pipeline's wall-time
  visible (reasoning tier dominates).
- **Embedding cache** (byte-identical) eliminates repeat embedding provider calls;
  a `nano` (1.5b) tier serves only non-reasoning decorative text (mission narrative).

### Improved (live, interactive graphs across the UI)
- **Domain analytics charts are now interactive** (the bar / funnel / donut used
  across all 7 department analytics): hover to highlight a series and dim the rest,
  with a contextual tooltip — % of total on bars, stage-to-stage conversion on the
  recruiting funnel, and share-of-total on the donut (with the center value
  switching to the hovered slice). Bars/segments animate in.
- **Sparklines feel live**: the "present moment" marker pulses, and hovering the
  trend reveals a crosshair + the value at any point (used on the Dashboard's
  safe-autonomy trend). This complements the already-interactive Precog forecast,
  Causal Discovery graph, Wargame resilience gauge, and Time Machine scrubber.

### Added (v4 Signature IP — Autonomy Wargaming, IP-4)
- **Adversarial resilience simulation.** New `services/wargame.py` stresses the twin
  with a CASCADE of shocks (named playbooks: supply shock, talent crisis, cyber
  cascade, regulatory storm) and scores how it holds up. Each department's fragility
  is computed from the REAL twin (skill confidence + recent adverse-event rate);
  damage COMPOUNDS as integrity falls; and each shock's response is classified
  autonomous vs human-in-loop by severity. Returns a resilience score + grade, the
  integrity curve, the weakest link, and the safe-response rate under stress.
  `GET /wargame/playbooks`, `POST /wargame/run`. Tested (5 cases: compounding
  degradation, robust-vs-fragile, safe-response classification, custom cascade).
- **Wargame mode on Reality Experience** (a fourth mode; the mode toggle is now a
  2×2 grid so labels never wrap): a playbook picker, an animated resilience gauge +
  grade, the per-shock integrity cascade with autonomous/human badges, and the
  weakest-link verdict. Verified live: the cyber cascade left the org at 19.6%
  integrity (grade F), engineering the weakest link.

### Added (v4 Signature IP — Enterprise Time Machine, IP-3)
- **Decision replay + counterfactuals.** New `services/time_machine.py`: scrub the
  org's real decision history (the append-only stream of governed executions),
  reconstruct the north-star (safe-autonomy-rate) AS OF any past moment from the
  decisions up to that point, and run a **real counterfactual** — recompute the
  same metric with ONE historical decision flipped (approve / fail / escalate). All
  from real execution rows, nothing fabricated. `GET /time-machine/timeline`,
  `/state`, `POST /counterfactual`. Tested (5 cases: classification, state-as-of,
  approve raises / fail lowers the rate, missing execution).
- **Replay mode on Reality Experience** (a third mode beside Shock and What-If, no
  new nav): a Time Machine panel with a rewind slider (the reconstructed rate as of
  any moment) and a decision list where picking one runs the counterfactual live
  (actual vs counterfactual rate + delta). Verified live: 166 real decisions,
  approving a fallout decision moved the rate 60.2% → 60.8%.

### Improved
- **Reality Experience space usage.** The Learning State (Recent Outcomes) and
  Reality Feed panels now fill their column height instead of capping at a fixed
  height and leaving dead space.

### Added (v4 Signature IP — Causal Discovery, IP-6)
- **Auto-inferred causal structure.** New `services/causal.py` discovers likely
  cause→effect links between departments from real data — no LLM, no hand-drawn
  graph. It builds each department's daily adverse-event series (failed / blocked /
  overridden executions) and measures **lagged Pearson cross-correlation**: if a rise
  in A's trouble reliably precedes B's by a day, that surfaces as A→B ("attrition in
  Eng → deploy delays → SLA breaches"). `GET /causal/discover`; honest about thin
  data (`insufficient`). Tested (5 cases incl. a planted lead-lag recovered as a link).
- **Interactive Causal Discovery graph** — a new tab in Knowledge beside the Topology
  Map: a directed graph with department nodes (sized by adverse-event volume) and
  animated arrows (a moving dash = "leads by a day"), colored by strength. Hover a
  node to isolate its links, hover an edge for strength/lag, plus a ranked link list.
  Verified live: inferred human_resources→finance (r 0.73), customer_support→marketing
  (r 0.73), and more from real execution history.

### Added (v4 Signature IP — Precog Org-Health Forecast, IP-5)
- **Forecast the north star.** New `services/forecast.py` — an honest OLS linear-trend
  forecaster with a 95% residual-based prediction interval (no LLM, deterministic,
  handles gaps, clamps rates to [0,1]). `GET /metrics/forecast` projects the
  safe-autonomy-rate and daily volume `horizon` days out from the real daily series,
  with a plain headline (current → projected, direction, R² fit). Too little history
  returns `insufficient` rather than a fabricated curve. Tested (7 cases: trend
  direction, band ordering, clamping, gap handling, insufficient-history).
- **Precog section on Org Pulse** (no new nav): an SVG chart of the observed
  safe-autonomy history, the projected trend (dashed), and the widening 95%
  confidence band, with a headline projection. Verified live: 8 observed days →
  14-day projection (55.9% → 35.5%, declining, R² 0.18).

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
