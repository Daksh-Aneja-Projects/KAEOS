# Changelog

All notable changes to KAEOS are documented here. This project adheres to
[Semantic Versioning](https://semver.org/).

> **On version numbering.** The git tag series (`v1.0.0` ... `v1.3.0`) is the
> authoritative release history. The `2.0.0` / `2.1.0` / `2.2.0` blocks further
> down were internal upgrade-sprint numbering from 2026-07-25 that was never
> tagged; the `1.x` line supersedes them. `APP_VERSION` and the frontend
> `package.json` now track the tag series.

## [Unreleased]

### Fixed - CI (e2e-mock lane)
- **`test_26_billing_reality_truth` referenced a renamed ROI key.** The `/billing/roi`
  response key was renamed `autonomous_executions` -> `safe_autonomous_executions` in
  the "one definition for safe autonomy" change (v1.3.0), but this e2e test was not
  updated, so it failed with `KeyError` against the live endpoint. Test-only fix,
  aligned to the endpoint's real contract; verified green against a live fake-LLM
  backend (10 passed).

### Added - closed the remaining known-limitation gaps with real logic
- **Prompt-injection detection + neutralization layer** (`app/services/prompt_guard.py`).
  A curated pattern battery scores untrusted content (instruction-override,
  role-manipulation, prompt/secret exfiltration, guardrail-bypass, tool/command
  smuggling, data-exfiltration, fake-role-turn, encoded-payload); matched command
  spans are redacted and untrusted text is fenced as data before it reaches an LLM.
  Wired into the ingestion pipeline (high-risk signals are quarantined). Layers with
  the existing source-authority weighting and HITL gates. 18 tests.
- **Erasure now reaches the blob layer and survives backup restores.**
  `app/core/polystore/blob_store.py` deletes the actual stored files (local FS +
  best-effort S3/GCS) during `erase_subject`/`purge_tenant`. A new `deletion_journal`
  table (migration `0026`, RLS-scoped) records every erasure (employee id + SHA-256
  of email, never raw PII); `POST /privacy/erasure/replay` re-applies them after a
  restore, matching email-only entries by hashing live rows. 7 tests.
- **Real semantic search on the SQLite dev path.** When no cloud embedding key is
  set, the router routes embeddings to a reachable local Ollama `nomic-embed-text`
  instead of non-semantic pseudo-vectors (scoped to SQLite so pgvector's fixed
  dimension is never disturbed). 5 tests.
- **Audit-readiness controls evidence.** `GET /compliance/controls`
  (`app/services/compliance_controls.py`) inventories the implemented technical
  controls, maps each to SOC 2 / ISO 27001 / GDPR / SOX criteria with code+test
  evidence, and explicitly lists the external items (attestation, pen-test) it does
  NOT claim as satisfied. 5 tests.
- **Compliance dashboard UI** now surfaces the above: the Compliance tab renders an
  Audit-Readiness Controls panel (implemented/operational/external counts, framework
  coverage, per-control evidence, external items honestly marked) and a Data Subject
  Erasure (GDPR Art. 17) panel that drives `POST /privacy/erasure` and
  `POST /privacy/erasure/replay` with a confirm guard. De-orphans the DSAR/erasure
  capability that previously had no UI. Verified live in the browser.

### Performance - test/dev loop
- **Unit lane parallelized with `pytest-xdist`.** CI now runs
  `pytest tests/ --ignore=tests/e2e -n auto`; the lane is per-process in-memory
  SQLite, so every xdist worker is fully isolated. Measured ~2.4x on this suite
  (219s -> 90s, 406 passed). The e2e lane stays serial by design (it shares one
  live backend). Also tagged the real-Ollama embedding test `@pytest.mark.ollama`
  so the fake-LLM lane deselects it.
- **Note on the gate LLM path:** the Gate 4 debate (an inherently sequential
  5-call adversarial chain) runs only on actions already cleared past the HITL
  gate, so there is no provably-safe "skip when the outcome can't change" case,
  and heuristic turn-skipping would weaken the gate. Left untouched on purpose
  (never weaken a gate for speed). Bigger LLM-latency wins remain hardware-bound.

### Changed - documentation accuracy (limitations review)
- **Known-limitations docs re-verified against the live code and corrected**, then
  updated again to describe the capabilities added above. Touched
  `docs/KNOWN_LIMITATIONS.md`, `README.md`, `docs/SECURITY_MODEL.md`,
  `docs/DEPLOYMENT.md`:
  - RBAC restated as **default-deny** with **199 of 212** write endpoints gated
    (was "106 of 132"); the remaining 13 are a reviewed allowlist. Locked by
    `test_default_deny.py`.
  - Retention sweep documented as **leader-guarded**; the **L2 fine-tune bridge**
    and **Redis-backed shared rate limiter** documented as live (were stale).
  - Security audit logging coverage updated to ~30 modules (was ~20).

Verified: full non-e2e unit lane **404 passed** before these last two additions,
and the affected + new suites (75 tests) green with them; migration chain applies
to a single head `0026`.

## [1.3.0] - 2026-07-27 - "Gate Integrity"

Pre-submission remediation: three defects in the gate pipeline that could let a
high-consequence action bypass its human, plus the repository presentation pass.

### Fixed - gate pipeline (security)
- **`hitl_pre_approved` was derived from the wrong signal.** The mission engine
  set both `has_human_approver` and `hitl_pre_approved` from `step.hitl_required`
  - the *requirement*, not evidence an approval occurred - and Gate 3 reads that
  flag to skip the entire confidence check including the high-consequence forced-
  HITL branch. `MissionStep` now persists an approval record (`approved_by`,
  `approved_at`), written only by `resolve_hitl_step`; the engine derives both
  flags from it, carries the real approver identity into the SOX check, and
  refuses to execute a `hitl_required` step that has no approval record
  (re-gates to `PENDING_HITL`). (migration 0023)
- **Gate 3's confidence ceiling failed OPEN.** A failed tenant-ceiling lookup
  (Redis/DB outage, cold cache, provider timeout) applied no cap at all, so a
  weak model silently regained full autonomy exactly when the system was least
  healthy. It now fails closed via the new `FAILSAFE_CONFIDENCE_CEILING`
  (below the autonomous-execution threshold), logs at `error`, and emits gate
  and activity-feed events so the failure is visible in the UI, not just logs.
- **`hitl_pre_approved` was reachable from a request-controlled context dict.**
  It is now a keyword-only argument on `AgentExecutor.execute_skill`;
  context-supplied values are stripped at the executor, and
  `POST /skills/{id}/execute` strips `hitl_pre_approved` and `has_human_approver`
  from the request context before it reaches the compliance check. All
  `execute_skill` call sites audited.

### Changed - safety controls
- **Explicit `always_hitl` marker replaces substring matching.** The
  always-route-to-a-human guarantee depended on naming convention (renaming
  `wire_transfer_approve` to `treasury_settle` silently made it autonomous), and
  the logic was duplicated with drift between the runtime gate and the `/skills`
  route. `Skill.always_hitl` is now authoritative and is evaluated by one shared
  helper, `app/services/consequence.py::is_high_consequence`, called from both
  sites; tag inference remains as an escalate-only fallback. Seeders and the
  workforce generator backfill the flag so behaviour on existing data is
  unchanged. (migration 0024)
- **Three swallowed exceptions on security paths now fail closed.** PII log
  redaction suppresses the payload instead of emitting the unredacted message
  when redaction raises; the Autonomy Dial holds the strictest threshold it has
  evidence for instead of reverting to the platform default on a lookup failure;
  the mission planner plans a human checkpoint instead of assuming 0.82 when the
  threshold cannot be resolved.

### Removed
- Dead duplicate `RateLimitMiddleware` in `app/core/redis.py` that failed open
  when Redis errored. Nothing imported it (`main.py` registers the one in
  `app/core/middleware.py`, which correctly degrades to an in-memory window); it
  was a fail-open landmine shadowing the live class by name.
- Internal planning artifacts untracked from the repository (kept locally):
  the vision / v2-upgrade / Starlette / navigation-audit / performance plans.
  They are living working documents, they name internal review process, and one
  carried dev-box hardware specs. The one durable public finding (why splitting
  the gate pipeline across a nano model is net-negative on a 6GB GPU, and why
  compliance verdicts are deliberately not cached) moved into the performance
  section of `docs/ARCHITECTURE.md`.

### Verified
- The published Python version now matches what is actually built and tested
  (3.12: CI, Dockerfile, and the ruff target). The previous "3.11+" badge was an
  untested claim - the tree parses under 3.11, but no lane exercises it.

### Documentation
- README restructured from 1,253 lines to ~150, with everything relocated (not
  deleted) into `docs/`: `ARCHITECTURE`, `FEATURES`, `API`, `CONNECTORS`,
  `BYOK`, `BENCHMARKS`, `SECURITY_MODEL`, `TESTING`, `SETUP`,
  `KNOWN_LIMITATIONS`. Every factual claim, number, benchmark result and
  limitation preserved verbatim.
- Fixed documented inconsistencies: the minimum-env-vars table omitted
  `ADMIN_SECRET` / `ADMIN_EMAIL` / `ADMIN_PASSWORD` while Quick Start said the
  app refuses to boot without them; the 4GB RAM prerequisite contradicted a
  default model targeting a 6GB GPU; the architecture diagram listed SAML in the
  auth box while the SSO section calls SAML roadmap; the execute stage was
  described two different ways; the project-structure tree mislabelled
  `services/skill_executor.py` as the 7-gate pipeline (the gates are in
  `app/agents/runtime.py`); `docs/` and `NOTICE` were missing from the tree.

## [1.2.0] - 2026-07-26

### Added
- **KAEOS speaks agent - MCP endpoint + Company Skills File** (the machine-facing
  interface; `app/api/routes/agent_interface.py`, `app/services/skills_file.py`):
  - `POST /mcp` - a Model Context Protocol endpoint (JSON-RPC 2.0 over
    streamable HTTP): `initialize` / `ping` / `tools/list` / `tools/call`, with
    six governed tools (`query_company_brain`, `list_skills`, `execute_skill`,
    `get_safe_autonomy_rate`, `list_pending_approvals`, `export_skills_file`).
    Any MCP-speaking agent can discover and operate KAEOS.
  - **No side door, by construction**: the MCP layer is a thin protocol adapter
    that forwards in-process (httpx ASGI transport, caller's auth headers) to
    the SAME governed REST routes a human hits - identical 7-gate pipeline,
    RBAC (`execute` still requires the operator role), and tenant isolation.
    An agent executing a gated action receives `PENDING_HITL` and waits for a
    human like everyone else.
  - `GET /brain/skills-file` - the Company Brain exported as an executable
    Company Skills File: operating rules and skills with confidence tiers,
    compliance tags, and governance instructions, grouped by domain/department,
    as agent-ready markdown or structured JSON.
  - Verified by `tests/e2e/test_30_agent_interface.py` (15 tests: handshake,
    tool catalog, every read tool, both export formats, JSON-RPC error paths,
    and a real skill execution through MCP on live Ollama). Suite grows
    426 -> 441 tests across 30 files.

### Added (from previous unreleased work)
- **KAEOS Foresight** (`/platform/foresight`): a fifth reality capability that is
  autonomous and prescriptive, where Shock / What-if / Wargame / Replay are
  reactive. Those four require the executive to already know which question to
  ask; Foresight sweeps the whole shock catalogue against the live twin with no
  prompt and answers the two questions a CXO actually has.
  - **Pre-Mortem Radar** scores every scenario
    `exposure = likelihood x blast_radius x preparedness_gap`, where likelihood is
    evidence-weighted from the tenant's own signals and recorded shock outcomes,
    blast radius is a real twin traversal from the most connected node (the worst
    credible cascade entry point), and the preparedness gap is 1.0 when no
    mission or skill governs the scenario. Scenarios with no governed response
    surface as **Inevitable Surprises**. Each of the three factors is shown in the
    UI so the score is never a black box, and every item carries an `evidence`
    block naming what it was computed from - a low-data tenant reads as honest,
    not confident.
  - **Prescriptive Trajectory** composes existing sources (the real
    safe-autonomy series projected with the same `linear_forecast` the Precog
    route uses, missions in flight, the live HITL queue and gated mission steps)
    into a 30/60/90-day view of what KAEOS will do autonomously and where it will
    need a human.
  - **Commission a gap-closer**: one click drafts a mission targeting the
    scenario's gap. It is created in `PLANNING` for a human to approve, never
    auto-executed, and the draft is re-derived server-side so a client cannot
    dictate the narrative attached to a governed mission. Verified live: 18
    scenarios scored over a 117-node twin, and commissioning moved
    MERGER_INTEGRATION from gap 1.0 / exposure 0.240 to gap 0.78 / exposure
    0.187, off the Inevitable Surprises list.
  - Endpoints: `GET /foresight/premortem`, `GET /foresight/trajectory`,
    `POST /foresight/commission` (operator-gated). Covered by
    `backend/tests/test_foresight.py` (scoring is real, gap-closing measurably
    lowers exposure, coverage is tenant-scoped).
- **Ghost Executions surfaced in the Executive Cockpit**: the `predictive`
  engine's zero-prompt runs ("what the org is about to do without being asked")
  were fully built but headless - no UI showed them. Added to the existing
  cockpit rather than a new page, beside Pioneer Intelligence, flagging any run
  awaiting approval.
- **Model Evolution (Foundry Phase 3) is now reachable from the app.** The whole
  gated-promotion loop - evaluate a candidate against the tenant's baseline on
  held-out governed examples, then promote or reject - existed server-side and
  was tested, but had no UI, so a candidate could never actually be evaluated or
  promoted by a user. Added to the EXISTING AI Foundry page: tier + candidate
  selection, an evaluation run list showing baseline vs candidate scores and
  delta, `SIMULATED` flagging, Promote/Reject actions (Promote enabled only for a
  non-simulated winning run), and the fine-tune job list with submit. The roadmap
  strip said Phase 3 was "planned" while it was in fact live - corrected.
  Verified with a real local model, not a stub: baseline `phi4-mini` 0.0895 vs
  candidate `llama3.2:1b` 0.0526 (delta -0.0369, `simulated: false`), the
  candidate correctly did not win, and promoting it was refused with "only a
  candidate that won its evaluation can be promoted".
- **Event-mesh signals can now be actioned.** `POST /signals/{id}/respond`
  ("manually enact the governed response") had no client method and no control,
  so a signal that correlated to the twin was a dead end - OrgPulse could show
  `no action` but offered no way to act. Added a Respond control on unactioned
  signals in the existing OrgPulse feed. Verified live: an ingested regulatory
  signal correlated to legal, produced a BRIEFING response, and was enacted.

### Security
- **Starlette security ceiling lifted - all remaining backend advisories fixed.**
  KAEOS was pinned to Starlette 0.48.0 because no released FastAPI supported the
  1.x line (0.119.x capped `starlette <0.49.0`), which left every advisory
  patched only in >=1.x *structurally unreachable*. FastAPI 0.140.0 removed that
  cap, so the stack moved to **FastAPI 0.140.0 / Starlette 1.3.1**
  (`prometheus-fastapi-instrumentator` co-bumped 7.1.0 -> 8.0.2; 7.x caps
  `starlette<1.0.0`). This clears PYSEC-2026-161/248/249/1942/2280/2281,
  including the form-urlencoded DoS (GHSA-82w8) and the Host-header auth-bypass
  (GHSA-86qp). The `starlette >=1.0.0` ignore rule was removed from
  `.github/dependabot.yml`, and SECURITY.md now records every Starlette advisory
  as Fixed or Not-applicable - none remain "accepted".
- **Authorization-coverage lints no longer go blind on a framework change.**
  FastAPI now stores each `include_router` as one `_IncludedRouter` entry instead
  of flattening children onto `app.routes`, so the default-deny and RBAC-coverage
  tests (which walked `app.routes` and read `route.dependant`) found almost no
  routes - a lint that would have passed *vacuously* while hundreds of mutations
  went unchecked. Added `backend/tests/route_introspection.py`, a walker that
  enumerates leaf routes on both layouts (462 routes discovered, verified), plus
  `test_route_enumeration_is_not_vacuous` which fails loudly if a future change
  ever blinds the walk again. Runtime enforcement was never affected: gated
  routes still return 403 to a viewer (`test_viewer_denied_on_gated_endpoint`).
- `test_poisoned_host_header_cannot_bypass_auth_gate` no longer asserts the
  *vulnerable* `request.url.path` value as a precondition (which would fail on a
  patched Starlette, i.e. break on a security improvement). It now asserts the
  invariant that matters on both patched and unpatched versions: a poisoned Host
  yields 401 and never reaches the handler. The `scope["path"]` mitigation is
  retained as defense in depth.
- Frontend: cleared the `brace-expansion` DoS advisory (GHSA-mh99-v99m-4gvg,
  high) via a transitive lockfile bump; `npm audit` now reports 0
  vulnerabilities.

### Fixed
- **Outbound write-back was silently failing on every governed action.**
  `sync_engine.queue_outbound` always opened its own `AsyncSessionLocal` instead
  of using the caller's session, so the queue row was committed on a separate
  connection and transaction from the mutation that caused it. Two consequences:
  the write-back was not atomic with its action (a caller that rolled back could
  still leave a queued write for a mutation that never happened), and every
  actuation logged a swallowed `sqlite3.OperationalError: no such table:
  outbound_writes` - the queue simply never persisted. It now accepts the
  caller's session (`db=`) and flushes into that transaction, falling back to its
  own session only for background sweeps with no session in hand.
- **`benchmark.real_data` availability probes reported unloadable datasets as
  available.** `sales_crm_available()` / `available()` checked only that the
  file existed on disk, not that `pandas` (a benchmark-only dependency, not in
  `requirements.txt`) could be imported. Any environment with the data but
  without pandas got a hard `ModuleNotFoundError` where the caller's `skipif`
  guard should have skipped. Availability now means loadable.
- **CI backend-test green**: `Actuator.compute_drift` raised
  `TypeError: can't compare offset-naive and offset-aware datetimes` on the
  SQLite test lane, failing `test_drift_detects_untracked_write` and
  `test_reversal_is_not_drift`. `DateTime(timezone=True)` columns are tz-aware in
  Python but SQLite drops tzinfo on round-trip, so a DB-loaded `updated_at`
  (naive) was compared against an in-session `reversed_at` (aware). Added an
  `_as_utc` coercion that normalizes both sides to aware-UTC before comparison.
- **Fine-tune auto-eval robustness**: `model_evolution.run_evaluation` promised
  never to raise for a missing/unroutable provider, but `_generate` let a failed
  `router.complete` propagate - so a candidate model that can't be reached (a
  not-yet-deployed fine-tune id, or any env with a live provider that rejects the
  id) crashed the whole poll sweep and marked every job `FAILED`. It now degrades
  a failed generation to an empty, `simulated=True` result (forcing `win=False`,
  never promotable), matching the documented contract.

### Changed (hygiene)
- Removed redundant module-level `pytestmark = pytest.mark.asyncio` from 30 test
  files (the suite runs in asyncio auto mode, where it only mis-tagged sync tests
  and emitted `PytestWarning`s) and the now-unused `import pytest` lines.
- Migrated the last four Pydantic v1 `class Config` blocks
  (`core/config.py`, `schemas/rules.py`, `schemas/skills.py`,
  `schemas/elicitation.py`) to `ConfigDict` / `SettingsConfigDict`, clearing the
  `PydanticDeprecatedSince20` warnings.

## [2.2.0] - 2026-07-25 - "Enterprise Reach"

The client-deployment sprint: KAEOS now reaches humans and systems OUTSIDE the
app, with the same governance spine.

### Added
- **Notification delivery layer**: tenant-configured SMTP / Slack / webhook
  channels (secrets Fernet-encrypted, masked on read), delivery ledger, admin
  CRUD + real test-send + Settings tab. Wired to HITL-pending, mission
  checkpoints, SLA escalations, invite emails. (migration 0020)
- **Approver persona**: HITL notifications carry signed single-purpose
  approve/reject links (audience-bound JWT, 7-day TTL); opening one resolves
  the real approval with no session, same audit trail. Replay/tamper/expiry
  refused.
- **Weekly executive digest** (Mon 08:00 cron + on-demand): safe-autonomy-rate,
  lowest-autonomy skills, pending approvals, incidents, model spend, missions -
  every number from real ledgers, honest wording when a source is empty.
- **Department-scoped RBAC**: users.department (migration 0021) confines a user
  to their department's operational surface (data, agents, missions, HITL)
  while cross-domain aggregates (org pulse, the twin) stay readable - that
  correlation is the IP. Enforced at the 7 domain-router mounts + per-row;
  managed from UserManagement; sidebar/cmd-K nav gated.
- **Realtime bidirectional sync engine** (migration 0022): external systems
  push changes the moment they happen (HMAC-SHA256 authenticated ingest;
  canonical envelope + Workday/Salesforce native-shape normalization); governed
  KAEOS mutations queue durable write-backs dispatched through provider
  adapters (generic_rest proven over real HTTP; salesforce implements the real
  sobject calls and activates on credentials; workday honestly reports the
  missing customer tenant). Every crossing lands in the SyncLedger; inbound
  deletes are recorded, not applied.
- **SOAR security response**: integrated apps report breaches to the HMAC
  ingest; each becomes a real Incident and runs governed containment -
  quarantine connector, rotate ingest secret, disable account (CRITICAL only);
  below that, recommended actions for a human. Humans paged via
  security.incident.
- **Ops/DR**: pg_dump backup + plan-first restore scripts, OPS_RUNBOOK.md.
- **Compliance posture**: docs/COMPLIANCE_POSTURE.md - verified SOC2/GDPR/PII
  control map with file references and an honest organizational-gaps section;
  access-review CSV export (GET /auth/users/export.csv).
- **Dashboard enrichment** (real API fields only): lowest-autonomy skills,
  SLA-breach chips, execution sparkline, cost-saved bars, AP aging + invoice
  donut + top vendors, recruiting funnel + headcount donut, cockpit freshness/
  decay/elicitation panels, cost-by-tier fix, OODA gate chips.
- **Frontend test lane**: 43 vitest tests + Playwright smoke against the live
  stack; backend fast lane at 345 tests.

### Fixed
- py3.14 native suite crash (pyarrow/fastparquet) - CRM load fully isolated in
  a child interpreter.
- react-router CSRF advisory (GHSA-qwww-vcr4-c8h2): migrated to unified
  react-router v8; npm audit clean (0 vulnerabilities).
- Executive Cockpit confidence distribution rendered fractions as counts;
  Infrastructure cost-by-tier iterated wrong keys ("No data" always).
- Full-tree ruff clean; frontend build under verbatimModuleSyntax; default-deny
  allowlist documents the two HMAC-public ingest routes.
- UI polish sweep: truncation/tooltips/wrapping across dashboards, missions,
  HITL, settings; aria-labels on header icon buttons.

## [2.1.0] - 2026-07-25 - "Living Enterprise Twin"

Makes the Reality Experience twin the product's hero view and closes several
data-consistency gaps that made live departments look empty. All verified in the
browser against the production Postgres tenant with real Ollama.

### Added
- **Rich cross-domain Digital Twin.** `build_live_twin` now weaves a bounded
  sample of every domain's real records into the constellation - Customers
  (finance), Accounts (sales), Tickets (support), Contracts (legal), Incidents
  (engineering), Purchase Orders (operations) - each attached to its department,
  on top of the full Department -> Capability -> Agent -> Process backbone.
  `sample_twin_for_view` keeps the structural backbone and caps high-cardinality
  leaves per department so the graph stays legible; stats stay honest (computed
  from the full graph, with a "N of M nodes" badge).
- **Twin as the page hero.** `RealityExperience` rearranged: a full-width stat
  strip (no label wrapping), the twin as a tall full-bleed hero with a node-type
  legend and live simulation controls beside it, and a full-width Reality Feed
  event stream. `TwinGraph` gained distinct colors/radii for the six new record
  types. Verified across shock / what-if / replay / wargame.
- **`seed_workforce_backbone.py`.** Idempotently generates the Capability ->
  Process -> DepartmentAgent backbone for a tenant whose departments already
  exist (e.g. from onboarding), binding each to its domain pack.
- **The twin reacts live in every mode.** Shock already pulsed the constellation;
  What-If, Wargame and Replay now drive the same shockwave - the affected
  departments and their records light up (severity from the mode's own result).
  The Decision Center and Why Panel are unified: all four modes populate the same
  impact summary + reasoning chain (What-If verdict/blast/risks, Wargame
  cascade/weakest-link/grade, Replay counterfactual delta), instead of the
  panels sitting empty outside shock mode. Reality Feed reflowed to a readable
  full-width card grid.

- **A real shock-scenario catalog.** The shock simulator went from 8 mostly-generic
  events (two with tailored options, six falling back to "Standard Mitigation /
  Aggressive Recovery") to **18 bespoke scenarios** across six categories -
  Security & Reliability (Cyber, PII Breach, Ransomware, SEV-1, Outage), Legal &
  Regulatory (Regulatory Action, Contract Dispute, Product Recall), Financial
  (Liquidity Crunch, Budget), Commercial (Key Account At Risk, Vendor Failure,
  Supply-Chain), People (Exec Departure, Talent Exodus, Termination) and Strategic
  (M&A, Capability Loss). Every scenario has its own causal model and three
  tailored, scored decision options, and they target the right twin entity -
  Contract Dispute picks a real contract, Key Account At Risk an account, SEV-1 an
  incident. The event picker is grouped by category.

### Fixed
- **Compliance evidence 404 on SOC2/ISO27001.** The regulatory overview surfaced
  an evidence-pack button for every skill `compliance_tag`, but the evidence route
  only whitelisted 8 frameworks - so clicking a SOC2/ISO27001 (or SLA/I9) button
  returned "unknown framework". SOC2 and ISO27001 are now first-class frameworks
  (evidence packs assemble generically from tagged skills), and the overview only
  renders buttons for frameworks that can actually produce a pack, so non-framework
  tags no longer appear as dead buttons.
- **Fabricated field fallbacks in the workforce view.** Employee location,
  requisition department and time-off type showed invented defaults ("Remote",
  "Engineering", "PTO") when the real field was empty; they now show `-` like the
  adjacent columns. (A frontend-wide audit otherwise found the dashboards, views,
  components and platform pages fully API-backed - no hardcoded business data.)
- **Deployment adoption skipped the backbone.** `generate_department_structure`
  adopted an existing department (created by onboarding) but returned before
  creating its capabilities/processes, so `deploy_agents` found nothing to bind
  and failed with "no agents were deployed". Extracted an idempotent
  `_ensure_capabilities_and_processes` run on both the new-department and
  adoption paths. Skill creation is now idempotent on `skill_id` (a prior partial
  deploy no longer collides). Deployed capabilities are marked ACTIVE, not PLANNED.
- **Department dashboards never showed deployed agents.** Finance, Legal,
  Operations, Sales and Support read `dept.agent_definitions`; the API returns
  `dept.agents`. All five now render the real `DepartmentAgent` records (name,
  role, status).
- **Legal "Active Contracts 0".** The onboarding seeder marked every contract
  SIGNED, so the ACTIVE-only KPI read zero beside thousands of clauses. Contracts
  now carry a realistic status mix (mostly ACTIVE, with SIGNED/IN_REVIEW/
  EXPIRED/DRAFT), effective/expiry dates, values and AI risk scores.
- **Finance AP/AR twin vs. dashboard mismatch.** The twin's `FinanceState` summed
  Purchase-Order commitments while the Finance card summed open invoice balances.
  Both now read the same source (open AP invoice + open AR invoice balances);
  onboarding generates real AP invoices from received POs.

## [2.0.0] - 2026-07-25 - "Self-Improving Autonomy Platform"

Production-readiness release. All P0 honesty/security/procurement blockers closed;
P1 hardening (auth, limits, ops, exports, user management); all six governance
loops closed (L1-L5 + L7 - governed advice becomes self-improving autonomy);
enterprise auth complete (OIDC SSO, MFA/TOTP, SCIM); orphaned capabilities wired
to UI. See the sections below for the full detail.

Executing the phased v2.0 upgrade plan (an internal planning document, not published).
Thesis: harden the safety and ops substrate first (earn the right), then ship the
AI Foundry closed loop; the north-star metric is safe-autonomy-rate.

### Added (Data - comprehensive Kaggle-backed onboarding)
- **Real relational sales CRM.** `onboard_real_company` (tenant `tenant_realco`)
  now builds the FULL pipeline from the sales parquet - Accounts (real
  firmographics: industry, region, employee band, revenue band) -> Contacts ->
  Opportunities (real stage + ACV) -> Activities - all relationally linked, instead
  of a flat lead list. New `loaders.load_sales_crm` returns a referentially-consistent
  subset. At `--limit 50`: 50 accounts / 152 contacts / 153 opportunities / 746
  activities (scales ~10x at the default 500).
- **Real procurement.** Operations onboarding now writes a `PurchaseRequest` +
  `PurchaseOrder` per real PO (supplier, category, quantity, negotiated price,
  status) plus a risk Signal for every non-compliant/defective order - previously
  Signals-only. New `loaders.load_procurement_orders`.
- **Reality twin seeded from real data.** `seed_state_twin` derives the four
  Enterprise-State snapshots (Finance/HR/Ops/IT) from the onboarded rows - headcount
  & attrition from HR, AR from invoices, AP from POs, vendor incidents & supply-chain
  health from procurement, P1 incidents from engineering - so Org Pulse / cockpit /
  scorecard render live numbers instead of an empty twin. Tests:
  `tests/test_real_data_loaders.py` (skip when raw data absent).

### Fixed / Added (Production-readiness - P2 polish, round 2)
- **At-rest key decoupled from the JWT key.** Stored secrets (connector creds,
  SSO client secrets, MFA secrets) can now be encrypted with a dedicated
  `CONNECTOR_ENCRYPTION_KEY`, independent of the JWT-signing `SECRET_KEY`, so a
  leak of one signing context no longer compromises the other. Falls back to
  `SECRET_KEY` when unset (existing deployments decrypt unchanged).
- **Honest ProcessEngine docstring.** `workforce/orchestration/process_engine.py`
  claimed it "handles agent actions, human checkpoints, and fairness gates" - it
  is a sequential DAG state tracker that makes NO governance decisions. The
  docstring now says so and points to where the real 7-gate orchestration lives
  (the missions engine + agent runtime).

### Fixed / Added (Production-readiness - P2 polish)
- **WebSocket token no longer in the query string.** The live-feed WS handshake
  carried the JWT as `?token=` (leaks into proxy/access logs and browser history).
  It now rides in the `Sec-WebSocket-Protocol` header (`["kaeos-bearer", <jwt>]`),
  which the server reads and echoes; the query param remains a backward-compatible
  fallback. Tests: `tests/test_ws_auth.py`.
- **Domain-specific agent steps for the non-HR departments.** Finance, Legal,
  Sales, Support, and Operations agents were generated with a generic assess/act
  template; they now get real, domain-grounded `load -> analyze -> act` steps
  (ledger/GL, contract/playbook, opportunity/CRM, ticket/KB, runbook/SLA). Truly
  unknown domains still get an honest role description. Tests:
  `tests/test_domain_agent_steps.py`.
- **Staging compose secrets are required.** `docker-compose.staging.yml` no longer
  bakes in default DB passwords (`kaeos_staging_secure` etc.); the critical
  secrets now fail-if-unset (`:?`) like production, so a forgotten override can't
  ship a known password to a network-reachable staging box.

### Changed / Removed (Production-readiness - ops & cleanup)
- **Deep health probe.** `GET /health?deep=true` now additionally reports the
  reachability of non-critical dependencies (Redis, the LLM provider) for
  observability; the default readiness probe stays fast and only the primary
  datastore gates readiness (503). Tests: `tests/test_health_deep.py`.
- **Removed dead/misleading code.** Deleted `frontend/.../DecisionStudio.tsx` (an
  unimported component with a hardcoded "Vendor Bankruptcy / Enterprise Trust: 92%"
  fake header) and `backend/app/core/validation.py` (an unused preflight that
  logged a FAKE "Neo4j reachable" line and skipped Redis).
- **Version bump to 2.0.0** across the backend (`APP_VERSION`) and frontend
  (`package.json`), and this CHANGELOG cut for the release.

### Added (Production-readiness - enterprise auth, round 2)
- **MFA / TOTP second factor (P1-17).** RFC 6238 TOTP implemented with the stdlib
  (no new dependency). Self-service enroll -> confirm -> enable
  (`/auth/mfa/enroll|confirm|disable|status`), the shared secret Fernet-encrypted
  at rest (`user_mfa`, migration `0019`, RLS) and never returned after enrollment.
  Login now requires a valid code when MFA is enabled (returns a `mfa_required`
  challenge otherwise). Tests: `tests/test_mfa.py`.
- **SCIM 2.0 user provisioning (P1-17).** `/scim/v2/Users` (create / list with
  userName filter / get / PUT / PATCH active / DELETE-as-deactivate) lets Okta /
  Azure AD / OneLogin manage KAEOS users automatically. ADMIN-gated (the IdP
  authenticates with a KAEOS admin API key), tenant-scoped, and SCIM-provisioned
  accounts are SSO-only (unusable local password). Tests: `tests/test_scim.py`.

### Added (Self-improving autonomy - the loop is closed)
- **L2 External fine-tune bridge - the 6th and final loop.** Model evolution
  already measured a candidate and gated its promotion; the missing step was
  PRODUCING the candidate. New `FineTuneProvider` abstraction (real
  `OpenAIFineTuneProvider` + honest `NullFineTuneProvider` that fails clearly when
  none is configured - never fabricates a model), a `finetune_jobs` table
  (migration `0018`, RLS), `submit_finetune` (exports the tenant's curated positive
  examples and submits), and a 5-min leader-guarded `run_finetune_poll` job that
  polls to completion and **auto-triggers a real `ModelEvolutionRun`** on the
  fine-tuned candidate. Promotion stays human-gated. Routes: `POST
  /foundry/finetune/submit|poll`, `GET /foundry/finetune/jobs`. Tests:
  `tests/test_finetune_bridge_l2.py`. All six governance loops (L1–L5 + L7) now close.

### Fixed (Production-readiness - resilience UX)
- **Fetch-error UI across the top pages (P1-13).** OrgPulse, MissionControl,
  UserManagement, and all six department dashboards (Finance/HR/Legal/Sales/
  Support/Operations) swallowed load failures to the console, so a backend outage
  rendered as "No data yet" / "Department not deployed". They now distinguish a
  genuine outage from an empty state and render a retry-able error instead.

### Added (Self-improving autonomy - closed loops, round 2)
- **L3 Drift -> reconcile / auto-heal.** `compute_drift` only DETECTED drift.
  Added `Actuator.reconcile_object` (re-asserts the last governed `after_state` as
  a new governed, reversible action) and `reconcile_all`, exposed via
  `POST /actuation/reconcile` (operator-gated) so an out-of-band change is pulled
  back to the state KAEOS is accountable for. Tests: `tests/test_closed_loops_l3_l5.py`.
- **L5-reverse Autonomy governor.** The dial->gate path was wired but nothing wrote
  the dial FROM measured reality. New `autonomy_governor` service + 6-hourly
  leader-guarded job nudges each domain's `min_confidence` from the real
  safe-autonomy-rate and override/failure fallout - bounded band [0.60, 0.95], small
  steps, minimum evidence threshold. A new `auto_managed` flag (migration `0017`)
  means a human-set dial is NEVER overridden by the governor (human override wins).

### Added (Self-improving autonomy - closed loops)
- **L7 Missions -> governed actuation.** Mission steps ran advisory-only
  (`tool:"none"`, no `actuation`), so runtime Gate 5b never fired and missions
  could only recommend. `MissionStep` now has an `actuation` column (migration
  `0016`); a HUMAN-APPROVED step carrying a concrete actuation intent hands it to
  the runtime so Gate 5b performs the idempotent, reversible write AFTER every
  gate passes - turning missions from "recommend" into governed "do". Advisory
  steps are unchanged. Tests: `tests/test_mission_actuation_l7.py`.
- **L1 Outcome -> execution learning.** Recording a measured outcome now stamps
  `SkillExecution.outcome_type`, so the AI Foundry (which mines SkillExecution,
  not OutcomeRecord) curates on real outcomes, not just on completion.
- **L4 Event-mesh -> outcome.** When an event-mesh-spawned mission finishes, its
  terminal status is written back to the originating `ExternalSignal` (-> RESOLVED)
  and an `OutcomeRecord` is recorded (GOOD/BAD), feeding the L1 loop. Idempotent
  and scoped to `created_by=="event-mesh"`. Tests: `tests/test_closed_loops_l1_l4.py`.

### Added (Production-readiness - audit export & user management)
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
  `BrainError` with a retry. (The same sweep across the other top pages -
  OrgPulse, FinanceView, MissionControl, the 7 domain views, UserManagement - plus
  the orphaned-capability UIs, DSAR/billing/webhooks, remain a tracked follow-up.)

### Changed (Production-readiness - reliability)
- **API keys moved to a DB-backed store (P1).** The key store was a module-global
  JSON dict loaded once at import, so a key generated or revoked in one gunicorn
  worker / replica was invisible to the others until a restart - runtime revocation
  did not actually take effect fleet-wide. Added an `api_keys` table (migration
  `0015`, RLS on Postgres, only the SHA-256 hash stored) and routed every lookup,
  generation, and revocation through it (`core/auth.py`, the tenant middleware, the
  WebSocket auth, and the admin issue/revoke endpoints). Revocation now propagates
  immediately across all workers/replicas. Tests: `tests/test_api_keys.py`.

### Fixed (Production-readiness - honesty & hardening)
- **Removed over-labeled confidence/coverage (P1).** Template workflows no longer
  ship a fabricated `coverage_score=0.85` (now `0.0` until real runs measure it);
  template rules downgrade from `0.88/VERIFIED` to `0.5/INFERRED` (matching sibling
  Skills); the regulatory engine's LLM-synthesized rule is `INFERRED` not `VERIFIED`
  (its `outcome_validation`/`explicit_validation` are 0.0), and its result status is
  `RULES_SYNTHESIZED` instead of the over-claiming `COMPLIANCE_ACHIEVED`.
- **Service-to-service auth for the agent mesh (P1).** The agent-mesh / cost /
  model-routing mutations (`/infrastructure/agents/*`, `/cost/check|record`,
  `/models/route`, `/schema-mappings/propose`) were reachable by ANY authenticated
  viewer. They now require `require_service_or_role("operator")` - a valid
  `X-Service-Token` (machine-to-machine) or an operator role - and are removed from
  the default-deny allowlist (the enforcement test now recognizes the gate).
- **Distributed rate limiting + body-size guard (P1).** The rate limiter was
  in-memory per-process (N× the intended limit under `-w4`); it now uses a shared
  Redis fixed-window counter when Redis is reachable, falling back to in-memory
  only single-instance. Added a `BodySizeLimitMiddleware` that rejects over-large
  request bodies (413) before a handler allocates them (OOM guard;
  `MAX_REQUEST_BODY_BYTES`, default 10 MiB). Tests: `tests/test_middleware_limits.py`.

### Added (Production-readiness - reliability)
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

### Added (Production-readiness - enterprise auth)
- **Real OIDC single sign-on (P0).** Enterprise SSO was a 501 stub plus an
  in-tree mock middleware that accepted a literal `"mock_valid_jwt"` (an auth
  bypass primitive). Shipped a complete, real OpenID Connect Authorization Code
  flow (`app/services/sso.py`, `/auth/sso/oidc/authorize` + `/callback`): IdP
  discovery, `state`+`nonce` carried in a short-lived HMAC-signed token (stateless,
  multi-worker safe), authorization-code exchange over TLS, **RS256 id_token
  signature verification via the IdP's JWKS** plus issuer/audience/expiry/nonce
  checks (PyJWT), and just-in-time user provisioning that mints a normal KAEOS
  session (provisioned accounts get an unusable password hash - SSO-only, never
  password-loginable). Covers Azure AD, Okta, Google, and Auth0. Per-tenant IdP
  config lives in a new `sso_connections` table (migration `0013`, RLS on
  Postgres) with the **client secret Fernet-encrypted at rest and never returned
  by the API**; managed through an ADMIN-gated config surface
  (`/auth/sso/connections`). Deleted the mock middleware. SAML remains an honest
  501 that points callers to OIDC. Tests: `tests/test_sso.py` (13) cover signed
  state, secret encryption, real RS256 verification incl. nonce/audience
  rejection, JIT provisioning/reuse/deactivation, and the config surface.

### Fixed (Production-readiness - security)
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

### Fixed (Production-readiness - honesty)
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
  `/marketplace` domain-pack page.

### Added (v4 Signature IP)
- **Shock simulator upgrade: Scenario Comparison** (IP-2) - each shock run is now
  captured and ranked side-by-side by severity, with blast (impacted node count),
  a severity bar, and the executed decision, so single shocks become scenario
  planning. Real data (each run is a `/reality/shock` call), in Reality Experience
  (no new nav). Verified live: Cyber Incident → HR (sev 95) ranked above Employee
  Termination (sev 60).
- **What-If Scenario Simulator** (IP-1) - a second mode beside the Shock simulator
  in **Reality Experience** (no new nav). Propose a change in plain language and get
  a governed verdict (SAFE/RISKY/BLOCKED), a **real blast radius** computed from the
  tenant's data (executable rules + skills + departments actually in scope - not
  hallucinated), a rollback-time estimate, and (when the LLM is available) ranked
  risk factors with mitigations + a recommendation. Surfaces the previously-orphaned
  real `/simulation/what-if` endpoint, upgraded to compute the blast radius from the
  DB so it is meaningful even without a cloud model. Verified live end-to-end.

### Added (v3 - Regulatory & Risk Autopilot, Phase 6)
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

### Added (v3 - Sense-Decide-Act Event Mesh, Phase 5)
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

### Improved (performance - no reasoning/quality change)
- **Composite DB indexes** on the hot analytics read paths: `skill_executions
  (tenant_id, started_at)` and `cost_events (tenant_id, timestamp)` (migration 0012,
  idempotent). Every analytics endpoint (safe-autonomy, time-machine, causal,
  regulatory, cost telemetry) filters exactly on those; the query plan now uses a
  covering-index seek instead of a scan.
- **In-flight GET deduplication** in the frontend API client: concurrent identical
  reads (a page's mount fetch + a live-refresh tick + multiple components) share one
  request. Zero staleness (only collapses *concurrent* identical GETs), fewer calls.
- **Bounded debate generation**: the debate gate's LLM calls now cap `max_tokens`
  with ample headroom over the short JSON verdict - prevents a confused model from
  runaway generation without ever truncating a well-formed response.
- **Model strategy (researched, hardware-gated).** On the 6GB dev GPU the 7b cannot
  co-reside with a helper model (loading a 1.5b evicts the 7b), so tier-splitting to a
  lighter model would swap-thrash - verified and documented; nothing is routed to the
  lighter tier here. See the performance section of docs/ARCHITECTURE.md.
- **Async missions.** A gated mission step can take a while on a live model, so
  `POST /missions/{id}/advance` no longer blocks: it starts a background runner
  (own DB session, per-mission guard, stale-step crash recovery) and returns
  immediately; the UI polls `GET /missions/{id}` for live progress. Verified: advance
  returns in ~0.3s (was ~2 min), the runner executes steps server-side (sales
  RUNNING→DONE) and pauses at HITL. Same governance, same output - just non-blocking.
- **Per-model-tier latency measurement** surfaced in the Executive Cockpit (calls ·
  avg latency) from the existing CostEvent data - makes the pipeline's wall-time
  visible (reasoning tier dominates).
- **Embedding cache** (byte-identical) eliminates repeat embedding provider calls;
  a `nano` (1.5b) tier serves only non-reasoning decorative text (mission narrative).

### Improved (live, interactive graphs across the UI)
- **Domain analytics charts are now interactive** (the bar / funnel / donut used
  across all 7 department analytics): hover to highlight a series and dim the rest,
  with a contextual tooltip - % of total on bars, stage-to-stage conversion on the
  recruiting funnel, and share-of-total on the donut (with the center value
  switching to the hovered slice). Bars/segments animate in.
- **Sparklines feel live**: the "present moment" marker pulses, and hovering the
  trend reveals a crosshair + the value at any point (used on the Dashboard's
  safe-autonomy trend). This complements the already-interactive Precog forecast,
  Causal Discovery graph, Wargame resilience gauge, and Time Machine scrubber.

### Added (v4 Signature IP - Autonomy Wargaming, IP-4)
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

### Added (v4 Signature IP - Enterprise Time Machine, IP-3)
- **Decision replay + counterfactuals.** New `services/time_machine.py`: scrub the
  org's real decision history (the append-only stream of governed executions),
  reconstruct the north-star (safe-autonomy-rate) AS OF any past moment from the
  decisions up to that point, and run a **real counterfactual** - recompute the
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

### Added (v4 Signature IP - Causal Discovery, IP-6)
- **Auto-inferred causal structure.** New `services/causal.py` discovers likely
  cause→effect links between departments from real data - no LLM, no hand-drawn
  graph. It builds each department's daily adverse-event series (failed / blocked /
  overridden executions) and measures **lagged Pearson cross-correlation**: if a rise
  in A's trouble reliably precedes B's by a day, that surfaces as A→B ("attrition in
  Eng → deploy delays → SLA breaches"). `GET /causal/discover`; honest about thin
  data (`insufficient`). Tested (5 cases incl. a planted lead-lag recovered as a link).
- **Interactive Causal Discovery graph** - a new tab in Knowledge beside the Topology
  Map: a directed graph with department nodes (sized by adverse-event volume) and
  animated arrows (a moving dash = "leads by a day"), colored by strength. Hover a
  node to isolate its links, hover an edge for strength/lag, plus a ranked link list.
  Verified live: inferred human_resources→finance (r 0.73), customer_support→marketing
  (r 0.73), and more from real execution history.

### Added (v4 Signature IP - Precog Org-Health Forecast, IP-5)
- **Forecast the north star.** New `services/forecast.py` - an honest OLS linear-trend
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

### Added (v3 - Cross-Domain Autonomous Missions, Phase 3)
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
  telemetry, and the budget ring - all real, with honest $0 cost for local models.

### Added (v3 - System-of-Record Actuation, Phase 1)
- **Autonomy that DOES: governed, idempotent, reversible write-back.** New
  `services/actuation/` Actuator applies a mutation to a real backing
  system-of-record row (`sor_objects`), keyed by a deterministic idempotency key
  (a retry is a no-op that returns the original record, never a duplicate write),
  captures before/after state, registers a compensator (the exact inverse), and
  appends to the provenance hash-chain. New `action_records` table + `sor_objects`
  (migration 0009, RLS on both). API: `POST /actuation/execute` (operator-gated),
  `POST /actuation/{id}/reverse`, `GET /actuation/ledger`, `GET /actuation/drift`.
  Wired into the agent runtime as **Gate 5b** - a skill may declare an `actuation`
  intent and the write-back only fires *after* the compliance / fairness /
  confidence-HITL / debate gates pass, inheriting full governance (non-fatal: a
  failed write is recorded, not raised). Tested (create/update/delete, idempotent
  retry, reverse restores prior state, drift detection, reversal-is-not-drift).
- **Actions Ledger (UI).** A new tab in **Decisions** beside the Provenance
  ledger - what KAEOS *did* to a system of record (governed and reversible),
  distinct from the *decision* ledger. Status summary (applied/reversed/failed), a
  reconciliation banner (records in sync vs drifted outside the governed path), and
  a one-click Reverse on any applied action. Verified live end-to-end: three real
  governed writes recorded, a reversal restored prior state, drift stayed at zero.

### Fixed
- **Fairness Audit Log score showed "-".** The Trust & Governance fairness log read
  a non-existent `composite_score` field; the API returns `fairness_score`. Now
  shows the real score vs threshold, a PASSED/BLOCKED chip, and the rationale
  (the data was always live - only the display field was wrong).
- **Analytics "Live" badge overlapped the KPI cards.** A negative margin pulled the
  KPI grid up under the badge in every domain analytics view; removed it so the
  live-sync indicator keeps clear separation above the cards.

### Added (v3 - Outcome Intelligence Loop, Phase 2)
- **Decision → outcome learning loop.** Record a measured real-world outcome for a
  past decision (`POST /outcomes/{execution_id}`, GOOD/BAD/NEUTRAL) and it feeds
  back into the executing skill's confidence (GOOD +0.02, BAD -0.05) - so the
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

### Added (v3 - Autonomy Dial, Phase 7)
- **The Autonomy Dial** - executives set a per-department risk appetite (the
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
  one genuinely new insight from `GET /metrics/safe-autonomy` - *why* work fell out
  of autonomy (routed-to-human / overridden / edited / failed) - is now a row on the
  Dashboard. No duplicate navigation touchpoint. All real, no mock.

### Added (planning)
- **The v3 "Autonomous Enterprise" plan** (an internal planning document, not published): new,
  non-duplicative layers (system-of-record actuation, outcome-intelligence loop,
  cross-domain autonomous missions, enterprise flight simulator, sense-decide-act
  event mesh, regulatory autopilot, trust/autonomy-dial, omnipresent touchpoints).

### Fixed
- **Workforce Analytics showed 0% automation and 0 active agents** despite 140
  real executions and departments reporting 6/7/5 agents. `agents_active` counted
  an empty detail table instead of the denormalized `agent_count` sum; automation
  averaged an unpopulated `Department.automation_coverage` column. Both now compute
  from real data (agent_count sum; autonomous/total executions, per-department via
  a skill-department join with slug normalization) - the headline is ~86%, not 0%.

### Fixed (security-critical)
- `backend/docker-compose.prod.yml` connected the app as the DB **owner**, which
  silently disables row-level security (owners bypass RLS). It now connects as the
  non-owner `kaeos_app` role with a separate owner URL for migrations; the prod
  entrypoint runs migrations under the owner URL. Added a guard test.

## [1.1.2] - 2026-07-21

Security hardening release. Closes a Host-header auth-bypass vector surfaced by
the Starlette advisory review in 1.1.1, and records the disposition of every
open Starlette advisory. No functional changes to features.

### Security
- **Fixed auth-bypass (GHSA-86qp-5c8j-p5mr, in-code mitigation).** Starlette
  `<1.0.1` rebuilds `request.url` from the attacker-controlled `Host` header, so
  a malformed `Host: victim/health?x=` made `request.url.path` read `/health`
  (a public path) while the router still dispatched the real **protected** route
  from `scope["path"]` - skipping the token check and assigning the dev tenant.
  The upstream fix ships only in Starlette 1.0.1 (unreachable - no FastAPI
  supports 1.x), so KAEOS's security gates now key off the raw ASGI
  `scope["path"]` instead of `request.url.path`:
  - `app/core/tenant.py` - the tenant/auth public-path gate.
  - `app/core/middleware.py` - the rate-limit exemption and request-log path.
  - Regression test: `tests/test_tenant_middleware.py::test_poisoned_host_header_cannot_bypass_auth_gate`.
- **Advisory disposition table** added to [SECURITY.md](SECURITY.md) covering all
  six Starlette advisories: 2 fixed by upgrade (1.1.1), 1 mitigated in code
  (86qp), 2 not-applicable and dismissed (x746 - no `HTTPEndpoint`; wqp7 - no
  `StaticFiles`/Linux), 1 accepted/tracked (82w8 - ingress-mitigated DoS).

### Fixed
- **Frontend lockfile drift** - `frontend/package-lock.json` referenced
  `react@19.2.8` while pinning `react@19.2.5`, breaking `npm ci` (`frontend-build`
  CI job). Re-pinned `react` + `react-dom` to `19.2.8` in lockstep so the lock is
  consistent with `package.json`.

## [1.1.1] - 2026-07-21

Maintenance & dependency-security release. Fixes the CI dependency-resolution
break introduced around 1.1.0 and patches upstream Starlette advisories, with no
functional changes to the platform.

### Security
- **Starlette `0.38.6` → `0.48.0`** (via **FastAPI `0.115.0` → `0.119.1`**),
  clearing two upstream advisories:
  - **GHSA-f96h-pmfr-66vw** (HIGH) - DoS via `multipart/form-data` (fixed 0.40.0).
  - **GHSA-2c2j-9gv5-cj73** (MEDIUM) - DoS parsing large multipart files (fixed 0.47.2).
- **GHSA-wqp7-x3pw-xc5r** (HIGH, StaticFiles SSRF/NTLM on Windows) - **not
  applicable**: KAEOS serves no `StaticFiles` and deploys on Linux
  (`python:3.11-slim`). Alert dismissed with rationale.
- **GHSA-82w8-qh3p-5jfq** (HIGH, form-urlencoded DoS) - **accepted / tracked**:
  only patched in Starlette 1.3.1, which no released FastAPI supports and which
  breaks `require_role` routing. Mitigated at ingress (reverse-proxy body-size
  limit). See [SECURITY.md](SECURITY.md).

### Fixed
- **CI dependency resolution** - the previous `starlette==1.3.1` pin was
  un-installable against FastAPI (`starlette<0.39.0` required), failing
  `backend-test` and `backend-e2e-mock`. Now resolves on a supported combo.

### Changed
- Added **`.github/dependabot.yml`** - grouped, weekly updates for pip / npm /
  github-actions, with Starlette `>=1.0.0` ignored (FastAPI-incompatible; see
  SECURITY.md) so the impossible security bump stops recurring.

## [1.1.0] - 2026-07-21

The **Workflow, Analytics & Collaboration Platform** release. Turns the seven
department brains from read-only dashboards into an operational system: every
core entity now has a guarded lifecycle, live cross-domain analytics, ownership,
comments, automation, and a unified notification surface - all on real tenant data.

### Added
- **Shared workflow engine** (`app/core/workflow.py`) - declarative per-domain
  state machines with guarded transitions, per-target-state **role floors**,
  business **guard** callables, **SLA thresholds**, a `core_workflow_events`
  audit trail, and a tenant WebSocket broadcast on every transition. Illegal
  moves return 409 with the allowed set; foreign-tenant rows 404 (never confirm ids).
- **Per-domain analytics + workflow endpoints** across Finance, HR, Sales,
  Support, Operations, Legal, Engineering - `GET /{domain}/analytics` (live SQL
  KPIs, charts, insights), `/{domain}/workflows`, `/{domain}/workflow-events`,
  guarded `POST .../{id}/transition`, `POST .../workflows/{type}/bulk-transition`
  (per-id outcomes), and validated entity-**creation** endpoints with auto-numbering.
- **Org Pulse** (`/pulse`) - cross-domain health (insight-severity + SLA-breach
  weighted), unified needs-attention feed, live workflow activity, an **SLA
  Breaches** table, and one-click **Escalate all** (idempotent alerting).
- **Assignment & My Work** (`/my-work`) - assign any entity, per-user "my work",
  team workload, all cross-domain.
- **Comments & @mentions** on any workflow entity, with mention notifications.
- **Automation rules** (`/automation`) - declarative "when an entity dwells in a
  state past N hours, transition / assign / escalate"; rules validated against the
  live workflow registry, evaluated on demand.
- **Notifications & digest** - unified notification feed with unread counts,
  mark-read, and a one-call org digest; SLA/mention/automation alerts surface in
  the header bell alongside the HITL queue.
- **CSV export & saved segments** - export any workflow entity type; save named
  per-domain filters.
- **Live-feel UI** - a `LiveBadge` (WebSocket heartbeat + "synced Ns ago") on the
  main dashboards; domain views and analytics auto-refresh on tenant events.
- Alembic `0004_workflow` and `0005_workspace` (RLS-guarded on Postgres).

### Changed
- **Departments → Marketplace → Deploy** unified into one funnel: Departments
  shows what you run, the Marketplace is the catalog, and "Deploy This Pack"
  carries the chosen pack into the wizard (skipping its duplicate pack-picker).
  Standalone "Deploy" removed from the top nav.
- **ROI cost-saved** now derives transparently from live hours-saved × a
  documented loaded hourly rate (`LOADED_HOURLY_RATE_USD`, default $85) instead of
  reading an unpopulated metrics table - fixes the `$0` cost card while hours were
  non-zero. Rate is shown as a footnote for honesty.

### Fixed
- SLA-escalation dedupe now matches the `action_taken` column's `False` default
  (not just NULL), so re-running escalation never re-alerts open breaches.

## [1.0.0] - 2026-07-20

First public release.

### Added
- **Company Brain** - unified rules/skills/signals layer with a cross-domain
  knowledge graph and 5-dimensional confidence scoring.
- **Seven Department Brains** - HR, Finance, Legal, Sales, Support, Operations,
  and Engineering & IT Ops, each with domain agents running the gated pipeline.
- **Agent Factory** - create → approve → compile → deploy → orchestrate agents
  from a plain-English prompt.
- **Governance spine** - compliance / fairness / confidence-HITL / adversarial-debate
  gates, a hash-chained (tamper-evident) provenance ledger, and red-team checks. Gates **fail closed**.
- **AI Foundry (Phase 2)** - curates execution history into a tenant-scoped,
  RLS-isolated training dataset. (Model fine-tuning is a later phase and is
  labelled as such in-product - no models are trained today.)
- **Real-data benchmarks** - decision logic scored against seven public enterprise
  datasets; wins **and** losses reported transparently (`backend/benchmark`).
- **BYOK LLM routing** - LiteLLM gateway across Anthropic/OpenAI/Groq/Ollama with
  retry, circuit-breaker, budget gate, and per-call cost metering.

### Security
- Per-tenant **PostgreSQL Row-Level Security** on every tenant table, verified
  effective at startup (`assert_rls_effective`) and provable via `scripts/verify_rls.py`.
- No default/public login - the root admin is provisioned from `ADMIN_EMAIL` /
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
- **Security audit trail** (`SecurityAuditLog`) wired to real runtime events -
  auth successes/failures, RBAC denials, HITL decisions, config/connector/export
  actions - as a best-effort writer that never blocks a request.
- **Data protection** - right-to-erasure (`privacy_erasure`), a `DATA_RESIDENCY`
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
  fitness) are parameterized simulations, labelled as such - not learned models.
- Rate limiting is per-process (in-memory); use a shared limiter behind a
  multi-instance deployment.
- Pre-production checklist (load testing, a formal pen-test, and a one-time
  connector-credential re-encryption if upgrading) is in `docs/DEPLOYMENT.md`.
