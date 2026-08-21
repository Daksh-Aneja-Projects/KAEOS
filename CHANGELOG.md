# Changelog

All notable changes to KAEOS are documented here. This project adheres to
[Semantic Versioning](https://semver.org/).

> **On version numbering.** The git tag series (`v1.0.0` ... `v1.3.0`) is the
> authoritative release history. The `2.0.0` / `2.1.0` / `2.2.0` blocks further
> down were internal upgrade-sprint numbering from 2026-07-25 that was never
> tagged; the `1.x` line supersedes them. `APP_VERSION` and the frontend
> `package.json` now track the tag series.

## [Unreleased]

### Added - Brain upgrade, operator remediation, re-embed job, connector contract lane (2026-08-21)

The deferred integration-audit tail, executed:

- **The brain now watches eight signals.** Three new grounded observers join the
  original five: connected systems that stopped syncing (the twin drifting from
  reality), executable rules past their own declared half-life (decisions
  running on expired knowledge), and the fitness engine's top structural
  recommendation - the EvolutionEngine's analysis finally has a consumer. An
  empty tenant still proposes nothing: fitness reads 1.0 with zero
  recommendations, verified by test.
- **The brain shows its learning.** New `GET /brain/learning` exposes, per
  proposal kind, the decided counts, acceptance, mission outcomes and the
  resulting materiality weight - computed by the same pure function the
  reflection cycle uses, so the surface can never drift from the behavior.
- **A dedicated Company Brain page.** New tab beside Missions: the live pending
  panel, the full decision history with outcome badges, and "how it learns" -
  animated weight meters per idea kind with plain-English decision summaries.
- **Operator remediation is wired (M11).** The Operator Console now shows every
  scheduled background job's last-run heartbeat (a red job is failing every
  tick while the public status page stays green) and the durable job queue,
  with one-click requeue of terminally FAILED jobs.
- **Embedding re-embed job (M14).** `POST /knowledge/embeddings/reembed-stale`
  re-embeds vectors stamped by a previous embedding model - keyed on the model
  the router ACTUALLY produces vectors with, not the configured name, so the
  job converges. It refuses honestly on a simulated-only router and reports the
  required pgvector dimension migration instead of writing garbage when the
  store rejects the new width. `VectorStore.stale_vectors` backs it on both
  engines.
- **Vendor contract lane.** Ten mocked contract tests now pin what each bespoke
  connector promises the vendor: exact URLs and auth headers (QuickBooks realm
  queries, Xero org-scope header, NetSuite account hosts, GitHub API version,
  FHIR Accept), documented response-shape parsing, and graceful failure into
  the pull mesh. The live credentialed sandbox pass remains the documented
  boundary.
- **Dead-export sweep (M17).** ts-prune across the client: one dead layout
  constant removed; the ~100 unused type declarations it surfaced are the
  unadopted API contract types, kept deliberately (documented in
  KNOWN_LIMITATIONS).

### Changed - Performance hardening pass: pooling, N+1s, leaks, render waste (2026-08-21)

A production-scale sweep (three parallel audits over DB access, async/memory,
and frontend rendering; every finding re-verified at source before fixing).

- **Outbound HTTP now pools connections.** `guarded_async_client` used to build
  a fresh transport per call, so all ~40 outbound sites (webhooks, notifier,
  live connectors, sync engine) paid a full TCP + TLS handshake per request.
  The SSRF-pinned transport is now shared per `allow_private` mode and closed
  once at app shutdown; call sites unchanged.
- **Background tasks can no longer vanish.** Mission runners and event-bus
  automation handlers were fire-and-forget `create_task` with no reference - a
  GC'd runner permanently wedged its mission id, and a handler exception was
  swallowed silently. Both now hold strong refs; handler failures are logged.
- **Memory leaks closed.** The JWT revocation fallback set (grew per logout,
  forever), the failed-login tracker (grew per attacker-probed email), the
  in-memory cache bus (lazy-only expiry made unread keys immortal), and the
  HITL memory fallback (no TTL, unlike its Redis twin) all evict now.
- **N+1s and unbounded scans.** Drift detection now uses one GROUP BY instead
  of a query per systems-of-record object (it ran hourly per tenant); outbound
  delivery joins credentials instead of querying per connector; webhook counters
  are single atomic UPDATEs; the Company Brain reconciles outcomes with one IN
  query, deduplicates in one round trip, and dropped a useless per-row refresh.
- **Dashboards stopped hydrating whole tables.** `/brain/overview` runs 8
  aggregate round trips instead of 13 and fetches 3 thin columns instead of 200
  full Rule rows; `/evolution/state` computes its fitness sub-scores in SQL
  instead of loading every rule, fairness row, and execution into Python.
  The elicitation dashboard's total count was missing its tenant filter
  (cross-tenant count leak) and its pending list was unbounded - both fixed.
- **Event-loop hygiene.** Pipeline file-destination writes and CSV schema reads
  moved off the event loop (`asyncio.to_thread`), matching their siblings.
- **Frontend.** The knowledge-graph physics loop now parks itself once settled
  (it re-rendered every node at 60fps forever, with two O(n) lookups per edge
  per frame - now indexed); the status page and LiveBadge timers pause in
  hidden tabs; the workforce directory computes its six per-render list passes
  in one memoized pass; theme/auth/branding context values are referentially
  stable so a provider render no longer cascades through every consumer.

Second wave (the deferred list, executed):

- **More round trips gone.** KB-health dashboard 17 -> 11 queries; AI-inventory
  execution counts 3 -> 1; cost telemetry derives totals from its tier groups;
  model routing picks target + fallback tiers from ONE registry query instead
  of up to four sequential ones (this sits on the LLM-call path); /my-work
  hydrates assignments with one IN query per entity type instead of one query
  per row; scoped provenance verification batch-fetches out-of-scope parents
  instead of a lookup per row.
- **Bounded reads.** The reality twin samples employees and vendors like every
  other headline entity (it is a balanced constellation by design, not an
  HR-employee cloud); mission detail returns the newest 200 ledger events as
  thin columns; the foresight coverage corpus caps at the newest 1000 missions;
  the stuck-job reaper sweeps at most 500 per tick. The fair-lending cohort scan
  stays all-time by design (the JSON protected-class bucketing must remain
  portable Python), but now transfers only the two consumed columns.
- **Exports off the loop.** Rule export selects thin columns with a 50k ceiling
  and serializes in a worker thread; workspace CSV export serializes its 10k
  rows off the loop too.
- **Auth/SSO resilience.** The OIDC discovery cache gained a 1h TTL (a rotated
  jwks_uri used to wedge logins until restart) and serves the stale document
  through transient IdP outages; the fine-tune bridge now uses the SSRF-pinned
  pooled outbound client like every other external call.
- **Small fixes.** S3 delete builds and caches its client off the event loop;
  the MCP agent interface caches its in-process forwarding client; a WebSocket
  whose client vanished mid-handshake is unregistered immediately; the skill
  rate-limit guard counts once per request; the deployment poll and the polling
  hook's staleness ticker hold while the tab is hidden.

### Added - The Company Brain: self-proposed, human-governed missions (2026-08-21)

KAEOS reacted to signals; now it also reflects. The Company Brain observes a
tenant's operational reality from real rows KAEOS already keeps and PROPOSES its
own missions, closing the signal-to-mission loop from the other end.

- **Reflection cycle.** On a 6h cadence (or on demand), the brain observes the
  safe-autonomy-rate trend, cost trend, open systems-of-record drift, recurring
  mission failures, and the elicitation backlog, and synthesizes the most
  material into candidate missions. Every observation is grounded in a real row;
  a fresh tenant with no signals proposes nothing (never a fabricated problem).
- **Governed by construction.** A proposal carries no authority. It is inert
  until an operator approves it, and approval routes through the existing
  `plan_mission` so every spawned step still passes the 7 gates. The brain
  proposes, a human disposes, the gates execute.
- **It learns.** A rejected idea is suppressed for a cooldown (the brain
  remembers the 'no'); the weight of a KIND the human keeps rejecting - or whose
  missions keep failing - drops, so materiality is tuned by real acceptance and
  real outcomes. An approved proposal's outcome is stamped from the mission it
  spawned, closing the meta-loop.
- **Surface.** Mission Control gained a live Company Brain panel: priority rings,
  a reflect-now control, plain-English rationale and evidence, and approve /
  dismiss. New API under `/brain/proposals` (list / approve / reject) and
  `/brain/reflect`; migration `0057` adds `brain_proposals`.

### Added - Incremental pull cursors + six per-department connectors wired (2026-08-21)

- **M15.** The vendor-adapter base gained a reusable incremental-pull cursor
  (`updated_at_field` / `cursor_params` / watermark stamping); Stripe and
  ServiceNow now pull only what changed, GitHub and Zendesk are watermark-ready.
- **Connectors.** The four list-sync per-department connectors (finance
  accounting, engineering issue-tracker, healthcare EHR, procurement PO) are
  bridged into the pull catalog and inherit the scheduler + credentials + cursor;
  the credit-bureau connector is wired into loan-application intake with an honest
  no-score fallback. They talk to real vendor APIs and need per-vendor sandbox
  validation (KNOWN_LIMITATIONS).

### Fixed / Changed - integration-audit Phase 2+3: leverage what is built, then hygiene (2026-08-21)

Phase 2 hardened and connected what already existed; Phase 3 swept hygiene.

- **Security.** The main executor now neutralizes prompt injections in untrusted
  content instead of only fencing it; the per-tenant MCP tool allowlist is
  enforced (every tenant agent could previously call every registered tool); a
  federated swarm hash-match can no longer raise a skill's confidence or trust
  tier without this tenant's own local evidence; a failing red-team scan now
  costs the skill its autonomy (it was recorded and ignored); and the dead,
  cross-tenant-unsafe ChaosInjector was deleted.
- **Privacy / money.** GDPR erasure now also purges the graph store (a Knowledge
  node's name could carry a subject's PII); commission payouts get a hash-chained
  audit trail recording amount, approver and beneficiary.
- **Dead weight and cost.** ~15 dead speculative modules deleted; /neural/world
  (the heaviest read) is cached; the copilot no longer searches a permanently
  empty HR namespace; the semantic skill-search read path is wired; one shared
  WebSocket per tenant replaces one-socket-per-hook.
- **Hygiene.** Stale docstrings and comments corrected, marketing routed to a
  real department in the planner, legal de-islanded in the org graph, empty
  directory and untracked repo-root litter removed.

Several audit findings were refuted on hand-verification (the graph layers are
used, not dead; the HR "wrong tab" is already handled) and are recorded as such.
Four items are deferred (see KNOWN_LIMITATIONS): a re-embed job, per-adapter pull
cursors, OperatorConsole remediation actions, and a dead-export sweep.

### Added / Fixed - integration-audit Phase 1: the internal event fabric and the closed loop (2026-08-21)

The departments were islands and the intelligence engines terminated at
dashboards. Phase 1 wires the internal event fabric and feeds the one closed
learning loop the product is built around.

- **The event bus was dead - now it is the internal fabric.** `emit()` had zero
  callers, so `system_events` was never written and the customer webhook API
  (`POST /enterprise/webhooks`) could never fire. Wired the three lifecycle
  chokepoints (mission terminal, HITL decision, governed actuation) and added an
  in-process handler registry so departments react to each other's events.
- **The closed loop is fed.** Connector pulls now bridge into the event mesh
  (correlated to the twin) and embed into the RAG namespace the copilot grounds
  on; BYOK ingestion routes through the real scrub+vectorize pipeline instead of
  writing one activity row; drift detection gained a lifecycle so it no longer
  self-silences after the first hit; the inert, ungoverned precog loop was
  removed.
- **Learning and knowledge.** Elicitation answers become candidate rules through
  the maker-checker path; a reversed governed write corrects its decision
  memory (and the memory metadata write is now tenant-scoped).
- **Governance truth.** The provenance ledger now hash-chains gate refusals and
  post-execution overrides, not only successes; the two HITL stores reconcile
  (a mission approval retires the paired queue entry instead of orphaning it).
- **Cross-department automations.** HR offboarding spins up a governed IT
  deprovision mission; a lending adverse-action raises a compliance review; a
  support escalation raises an operations signal.
- **Department parity.** The workforce generator gives all ten departments real
  domain-grounded steps and rules; the support/operations litigable estate
  (tickets, purchase orders) can now be placed on legal hold; lending and
  procurement carry healthcare-grade gate policy (high-consequence decisions
  route to a human, amounts and lawful basis proven in the audit trail).
- **Connectors can become real.** A credentials panel wires the connect ->
  test -> sync lifecycle; simulated feeds are marked DEMO and can no longer
  pollute rule-mining, the mesh, or RAG.

Several audit findings were refuted on hand-verification (an SSO login flow and
the procurement agents already existed; a compliance-tag "silent skip" was
actually a documented non-blocking warning) and are recorded as such.

### Fixed - integration-audit Phase 0: billing integrity and four governance boundary defects (2026-08-21)

A five-track whole-system audit (department interlinking, cross-cutting
engines, frontend/backend coverage, governance pipeline, knowledge layer)
found five critical defects; four were fixed the same day and one was refuted
on re-verification.

- **The Stripe meter counted phantom rows that never ran.** Predictive-ops
  wrote SkillExecution rows stamped `QUEUED` - a status no gate produces -
  that nothing drained; usage rating counted every row in the period with no
  status filter, so never-executed predictions were pushed to the billing
  provider as metered work and diluted the safe-autonomy denominator. All
  execution counts now filter on the canonical governed vocabulary, and
  zero-prompt predictions enqueue a durable job that runs the skill through
  the FULL gate pipeline - a prediction can no longer pre-claim (or pre-waive)
  human review. The ghost-executions view reads the job queue, the honest
  source of truth.
- **Support agents ran raw LLM calls; one closed tickets on the model's own
  confidence claim.** The resolution agent set `ticket.status = RESOLVED`
  whenever the model's own JSON said resolved with confidence > 0.85 -
  inverting Gate 3's premise - and the KB agent wrote articles ungated. Both
  now route through the gated support runner (compliance/PII, fairness,
  confidence/HITL at a forced 0.79, debate, audit, provenance); the
  resolution agent only recommends, and ticket state changes remain a human
  action.
- **An emailed approval link could out-privilege the recipient's account.**
  HITL links fan out tenant-wide, and the signed-link path applied no
  department scoping, so a sales-scoped user could decide an HR pause their
  own session would be 403'd for. The execution's department is minted into
  the token and decide-time enforces the same scope rule as in-app.
- **Raw actuation writes and reversals lacked their consequence gates.** A
  money-shaped UPDATE at /actuation/execute applied on one operator's sole
  authority (the probe was name-only and never saw the payload), and
  /actuation/reverse had no gate beyond RBAC. Money-shaped writes now pause
  for approval like DELETEs, and consequential reversals enforce four-eyes:
  the identity that performed the action cannot also reverse it.
- **Refuted on re-verification:** "ECOA adverse-action notices issue
  ungated." The path already validates fail-closed against the registered
  ECOA checker (specific-reasons bar, prohibited-basis, receipt-anchored
  30-day clock) before persisting, is deterministic, and is ledgered.

### Fixed - the campaign tail: real-model verification, two governance defects, a pre-launch re-audit (2026-08-20)

- **The e2e lane ran on a real model for the first time this campaign** -
  439 passed / 4 skipped / 0 failed in 21m22s against local Ollama
  (qwen2.5-coder:7b), on a freshly seeded database (one of those four skips is
  now a pass - see below). It found two harness
  defects, both fixed: the runner booted uvicorn on a hardcoded port that
  belongs to another service on the maintainer's machine (the suite has already
  been bitten once by reporting on a backend that was not the one under test -
  358 bogus failures), and a cross-tenant enumeration test read ADMIN_SECRET
  straight from os.environ instead of through the conftest resolver, so it
  skipped itself on every normal local run rather than running. Everything that
  names the e2e port now says 8011 - runner, conftest default, and CI.
- **A debate-escalated mission step waited for a human instead of being stamped
  FAILED.** Gate 4's ESCALATED_DEBATE means "two agents disagreed, a person must
  rule on this", but the mission engine's pending-set did not list it, so the
  step fell through to the failure branch. That both lied about the outcome
  (nothing was tried) and dropped the decision on the floor: only an
  AWAITING_HITL step can be approved, so the escalation never reached the
  approval queue at all. The branch now reads execution_status.PENDING_STATUSES
  so the two vocabularies cannot drift apart again.
- **The workforce headline autonomy tile reports the same 30 days as the views
  an operator drills into from it.** It counted the tenant's entire history
  while /metrics/safe-autonomy, the /ops blended rate and its own module's
  /autonomy-trend all used 30 days, so the headline lagged every sibling and
  diluted recent improvement. It also stops re-deriving the north star locally -
  the same drift already fixed once in /billing/roi - which removes a full-table
  row pull, and the window now travels with the number so the UI names the
  period instead of implying "ever". (/billing/roi is deliberately all-time; it
  sits beside lifetime cost figures and says so.)
- **TrustGovernance no longer tells an operator the governance record is empty
  while it is still loading.** The component computed `loading` and never read
  it, so during the initial fetch the page asserted "No provenance entries yet",
  "No fairness audits recorded yet" and "No debates recorded yet".

### Changed - vocabulary, dead code, and lint (2026-08-20)

- **Every producer and consumer speaks the ExecutionStatus enum** (M2.6's
  vocabulary, now adopted): 120 bare string literals across the six gate
  functions and 42 domain agents, routers, seeders and services. Behaviour is
  identical - a StrEnum member IS a str - and proven so by the differential gate
  harness (36 runs, 0 mismatches) plus the full lane. Two sites that scored runs
  with `status.startswith("SUCCESS")` and `"SUCCESS" in status` now read a named
  SUCCEEDED_STATUSES set, so a future member merely containing the word cannot
  silently count as a success.
- **rag_fallback_rate is gone end to end** - a metric that could only ever read
  0% once SkillRouter was deleted, still rendered as a Command Center tile and
  narrated in the Evolution Timeline. Persistence was checked first, per the
  hours-saved precedent: no table stores it and a fully seeded database holds
  zero RAG_EXEC rows, so no migration was needed. The vacated tile now shows
  skills_used, which the payload already carried and nothing displayed.
- **The inert SkillRouter remnants are deleted**: the skill_routing prompt
  template, the DI provider with no callers, and a per-request PolystoreEngine
  the skills list route constructed and never read. PolystoreEngine.search_skills
  was deliberately KEPT and the reasoning written at the site - it is the only
  code that reads skill_embeddings, a table this system still writes on every
  skill create, so deleting the reader alone would turn a live, HNSW-indexed
  write path into a write-only subsystem.
- **eslint warnings 1368 -> 1235, errors still 0**: no-unused-vars 129 -> 0
  (100 dead import specifiers across 28 files, a `domain` prop 17 components
  accepted and never read, and state stranded by earlier extractions - including
  a hand-rolled Authorization header, which takes a stray bearer token out of a
  component) and the three stale eslint-disable directives, one of them
  file-wide. A stale disable does not sit idle; it hides the next real warning
  at that site.

### Security - pre-launch re-audit (2026-08-20)

Re-run of the standing pre-launch gate over the 84 commits since the v2.0.0
clearance. Scans clean: bandit 0 medium/high across 69,189 lines, pip-audit 0,
npm audit 0, no secrets in the shipped bundle.

- **A production boot may no longer adopt the demo tenant.** Booting a
  production-configured instance against a fresh Alembic-migrated Postgres
  proved the demo-seed gate holds - four populated tables, zero fictional rows -
  but showed the root admin being provisioned into `tenant_acme`, the id every
  fixture path in the tree writes to by name. Real records would then share a
  tenant with the demo data, so one mis-set ENVIRONMENT would mix fictional
  employees and invoices into live rows, and in a governance product you cannot
  afterwards tell which records were invented. Refused at boot now, the same
  fail-closed way a placeholder SECRET_KEY already was.
- **A wildcard CORS origin is refused in production.** The app allows
  credentials, so Starlette reflects the caller's Origin back for a wildcard -
  any site a logged-in operator visits could read authenticated responses. The
  shipped default was already explicit origins; this stops a deploy widening it.
- **validate_production_security is finally tested.** The boot-time gate between
  a careless deploy and an open one had no coverage at all, so every control in
  it was one careless edit from silently returning [] forever.
- **Authorization coverage re-verified; the audit's own finding REFUTED.** The
  audit flagged "no ratchet on authorization gates" and added one. That was
  wrong: `tests/test_default_deny.py` has enforced default-deny over every
  mutating route all along, through the dual-layout walker in
  `tests/route_introspection.py`, with a reviewed per-route allowlist and its own
  anti-vacuity guard. The duplicate was deleted. It also failed on CI in a way
  worth recording: written against the local FastAPI 0.115, it walked `app.routes`
  directly and saw 2 routes instead of 314 on CI's pinned 0.140, where
  `include_router` stores lazy `_IncludedRouter` proxies - the exact trap
  `route_introspection.py` exists to absorb, and the second time it has been hit.
  Its positive control is what caught the blindness. What survives is the
  verification: M2.1's 78-route HR split left 0 ungated HR mutating routes, and
  each of the 15 allowlisted paths was independently re-read and does carry
  another authenticator (HMAC body signature, Stripe signature,
  verify_admin_secret in the handler, a signed SAML assertion, or
  get_current_user on the caller's own account).
- Verified unchanged and holding: RLS refuses to serve when policies are absent
  or the app connects as the table owner; production refuses SQLite; migrations
  0053-0055 upgrade AND downgrade cleanly on real Postgres; the Stripe webhook
  verifies its signature and resolves the tenant from our own records, never the
  payload; the single upload endpoint is role-gated, size-capped,
  extension-allowlisted and passes uploads through prompt-injection
  neutralisation and PII redaction before they are persisted or embedded; log
  redaction covers passwords, tokens, API keys, emails and SSNs, and fails
  closed.

**Still open, and owner-owned** (carried from the 2026-08-15 audit; all three
are non-code): a tested database restore drill, SPF/DKIM/DMARC records for the
sending domain, and KAEOS's own Privacy Policy and Terms of Service. There is no
public legal surface today - `/departments/legal/privacy` is the product's GDPR
department, not KAEOS's own terms. These block a public launch; nothing in the
codebase does.


### Changed - S6 final: the gate pipeline is one gate per function (2026-08-20)

- **M2.2, the highest-risk item in the plan, done dead last as ordered.** The
  966-line runtime's _run_gates/_run_post_hitl monoliths are now six named
  gate functions (compliance+fairness, confidence/HITL, debate, execute,
  actuation, audit) under one explicit GateOutcome contract (None = proceed;
  a dict = the pipeline's terminal result), with _run_gates and _run_post_hitl
  reduced to thin orchestrators - the three-divergent-pipelines failure mode
  the original comments warned about is now structurally impossible. Every
  incident-encoding comment moved verbatim. One gate per commit, each proven
  behavior-identical against the pinned pre-split baseline by a new
  differential harness (scripts/diff_gate_equivalence.py: 36 branch-reaching
  pipeline runs comparing results, ordered boundary-call sequences and context
  mutations), which was itself proven able to fail before being trusted - the
  red-proof caught the harness's own first bug, then two planted defect
  classes (a fail-closed status lie and a call reorder).

### Changed - S6 wave 3: structure, hoisting, clarity (2026-08-20)

- **The hr god router is 18 sub-routers behind a byte-identical surface
  (M2.1 + M8.5).** 2121 lines became a 139-line assembler + one module per
  sub-domain; the ordered 78-route list and the OpenAPI baseline are proven
  identical (one published schema name pinned where a class move would have
  renamed it). Route shadowing refuted for this router by regex cross-match.
  Dashboard and metric-snapshot bodies pushed down into hr services.
- **Core no longer imports services at top level, and the boundary is a
  tripwire (M8.2).** The claimed 5-module cycle refuted: one top-level edge
  existed (a 13-line DI shim in the wrong layer, now in app/api); an AST test
  fails naming file:line on any new violation (proven red on a planted one).
- **Hot-path in-function imports hoisted where the tripwire can see them
  (M8.3).** 68 of 74 across runtime/skill-executor/hitl hoisted; the perf
  premise refuted by measurement (~5 microseconds per governed run) - the real
  win is that runtime.py's 42 dependencies are now visible to the layering
  gate; 3 kept lazy with named reasons.
- **Seeders log through logging (M2.5); the core-seed split refuted with an
  executable proof (M2.3).** 62 prints replaced; an AST tripwire keeps them
  out. Splitting core/seed.py breaks the NOW module-global contract two test
  files depend on - pinned as a test, prerequisite recorded.
- **Ten long functions that hid real seams, extracted (M2.4).** Map: 104
  functions >= 80 lines (plan said 112). Ten fixed favoring pure helpers;
  seven refuted by name as honest narratives; four tests added where a fixed
  branch had no cover, including a documented risk-signal guard that had never
  actually run.
- **A keystroke no longer re-renders the route tree; one theme-token source
  (M7.3 + M7.14).** Global search and the notification bell own their state in
  src/components/shell/; ThemeProvider writes the 16 genuinely duplicated
  tokens as CSS vars (the migrate-rules half refuted - rules already used
  var()), fixing token utilities that were pinned to dark hexes in light mode.

### Changed - S6: test speed, layering, consistency, frontend hardening (2026-08-20)

- **The unit suite runs in 4:15, down from 15:41 (M9.4).** The schema is built
  once per pytest worker instead of created and dropped on both engines around
  every test (four DDL passes over 256 tables each); isolation is a per-test
  DELETE sweep in reverse FK order. The two-engine design is untouched. Also
  fixes the known-flaky actuation approval test (the resume takes ~3s; a sparse
  bounded poll replaces the 0.3s sleep - sparse because a tight poll measurably
  starves the resume of the shared StaticPool connection).
- **The realtime broadcast bus is a service (M8.1).** ConnectionManager and the
  Redis fan-out moved verbatim to app/services/realtime.py; core, agents and
  services no longer import upward into a route module, pinned by an AST +
  sys.modules layering test.
- **One department alias map (M8.4).** The 'eight hardcoded rosters' claim was
  refuted by a full scan; the real drift was three partial copies of the
  Skill.department normalization map whose identity fallbacks leaked phantom
  slugs ('it ops', 'platform') into the ROI dashboard and wargame. One map now;
  the deliberately-different lookalikes (signal canon, mission ordering) are
  labeled and pinned as refutations so a future consolidation fails loudly.
- **Demo fixtures never load in production; dead SkillRouter deleted (M8.6,
  M8.7).** main.py imports the demo seed module only inside the SEED_DEMO_DATA
  branch (pinned by a subprocess test); SkillRouter had zero callers - the
  class, its test-of-dead-code and the dashboard's always-zero RAG_EXEC count
  are gone (rag_fallback_rate stays in the response for the frontend).
- **One execution-status vocabulary; the north star declared once (M2.6).**
  StrEnum for status/outcome_type and agent_state, values pinned to the DB
  strings; four private constant sets converged to zero. The live divergence
  was the autonomy governor counting a status value the column cannot hold
  (looser than the metric it governs); five safe-autonomy consumers now read
  one SAFE_AUTONOMOUS_STATUSES set, tripwired by identity. Two real behavior
  defects found were deliberately NOT folded in (a debate-escalated mission
  step shows FAILED; the workforce headline tile uses an all-time window) -
  spawned as separate tasks.
- **Frontend (M7.10, 7.11, 7.13, 7.15, 7.16).** Theme toggle no longer remounts
  the whole page (ThemeAdapter renders one root element in both modes);
  CountUp animates via rAF + textContent (zero re-renders per frame);
  rules-of-hooks and static-components are back at error and caught two real
  shipped bugs (Sparkline's conditional useState, SkillContractViewer's
  in-render component); http.ts got its first 16 tests, an LRU-bounded SWR
  cache, and the admin secret is no longer stored in cache keys.

### Changed - S5 scale and replicas (2026-08-20)

- **The gate pipeline no longer holds a pooled DB connection (M6.1, the top
  ceiling).** A department endpoint entered the multi-LLM gate pipeline (240s
  LLM timeout) with its request session's read transaction open, pinning one
  pooled connection - ~15 concurrent governed runs exhausted a worker's pool.
  The request session is now committed at pipeline entry (audited: every gated
  caller enters read-only; expire_on_commit=False keeps loaded objects live),
  and the mission engine releases its background session the same way.
- **Redis outages heal (6.3, 6.4).** get_redis() re-probes a dead Redis every
  15s (bounded ping, failed probes close their client); the polystore CacheBus
  re-probes every 30s and upgrades from its in-memory fallback in place.
- **HITL pending list is O(pending), not O(keyspace) (6.5).** Per-tenant index
  set + one MGET replaces KEYS * + N GETs on a 30s poll from every open tab;
  self-healing, with a one-time SCAN backfill for pre-index records.
- **Job queue drains concurrently (6.6).** Bounded concurrency (semaphore, own
  session per outcome write) inside the leader's tick; one slow LLM handler no
  longer starves the queue or pins a connection while it waits.
- **Startup bootstrap is serialized across workers (6.7).** All schema/seed
  steps run under a dedicated bootstrap LeaderLock - serialized, not skipped,
  so no worker serves against a half-built schema and check-then-act seed races
  are gone. Also fixes a connection leak in LeaderLock.release() when the
  advisory unlock fails.
- **WebSocket fan-out is concurrent (6.8).** Sends gather per tenant and across
  tenants: N stalled clients cost one timeout total instead of N x 5s serially
  in the subscriber loop (worst case was 250s per message per tenant).
- **Per-tenant stage-timing buffers (6.2).** One busy tenant can no longer
  evict every other tenant's /metrics/latency entries (bounded per tenant,
  LRU-capped across tenants).
- **Bounded scans (3.7, 3.8).** /reports/compliance counts all five frameworks
  in one pass (tag matching now anchored - 'EU_GDPR' no longer counts as GDPR);
  erasure replay builds its email-hash index once per tenant per pass instead
  of streaming ten tables per journal entry.
- **Cheaper middleware, bounded rate-limit memory (3.9, 6.9).** RequestId,
  BodySizeLimit and SecurityHeaders are pure ASGI (no per-request task group +
  stream pair each), byte-identical behaviour on starlette 0.38 and 1.3.1; the
  in-memory rate-limit windows evict idle callers and are hard-capped.

### Changed - S4 governance tail (2026-08-20)

- **Healthcare's state machines are reachable over HTTP (4.4).** healthcare
  declared two WorkflowSpecs (encounter, clinical_task) but shipped no
  single-entity transition endpoint and no `/workflow-events`, so the only way
  through them was the gated agents. Added `POST /healthcare/encounters/{id}/transition`,
  `POST /healthcare/tasks/{id}/transition`, `GET /healthcare/workflow-events` and
  `POST /healthcare/workflows/{entity_type}/bulk-transition`; lending and
  procurement gained the bulk-transition endpoint they lacked. All ten
  departments now expose the same workflow surface. HealthcareView renders the
  shared WorkflowActions on encounters and clinical tasks; the transition toast
  now reads "moved from Open to Triaged" instead of raw enum names. OpenAPI
  baseline refreshed (671 -> 677 operations).
- **Legal exposure is money, not prose (4.7).** `leg_matters.estimated_exposure`
  was `Text`; it is now `NUMERIC(18,2)` end to end: the API takes a non-negative
  Decimal (prose is a 422) and returns a JSON number; migration `0054` converts
  salvageable legacy strings ("$1,250,000.00") and NULLs the rest rather than
  failing. LegalView shows it as currency and the New Matter form exposes it.
- **Five genuine foreign keys (4.8).** `mission_steps.mission_id`,
  `action_records.execution_id`, `department_agents.blueprint_id` /
  `.deployed_agent_id` and `eng_engineers.hr_employee_id` always name a sibling
  row, so the database now says so (migration `0055`, after an orphan sweep:
  dangling nullable pointers are NULLed, orphan mission steps are deleted, both
  logged). `POST /actuation/execute` now verifies a client-supplied
  `execution_id` tenant-scoped (404, never a 500 IntegrityError).
- **Startup seed guard is tenant-scoped (4.12).** `seed_domains_if_empty` counted
  the sentinel table across all tenants while every seeder's own guard is scoped
  to `tenant_acme`, so on a multi-tenant dev database the first tenant with HR
  rows suppressed the demo seed forever. The orchestrator now uses the same
  predicate as the seeders (dev/demo only: it runs under `SEED_DEMO_DATA` and
  not production-like).
- **Frontend (4.13, 4.14).** LendingView accepts the `analytics` tab it already
  renders; SupportView's tab bar has the roving `tabIndex` its nine siblings have.

### Changed - S4 governance, behaviour-changing (2026-08-19)

- **HR transactional money is exact Decimal, not binary Float (4.6).** Payroll
  totals, payslip pay, compensation base and benefit-plan costs (10 columns
  across hr_payroll_runs / hr_payslips / hr_compensation / hr_benefit_plans) moved
  from `Float` to `NUMERIC(18,2)`, matching the finance tables - a paycheck must
  be exact to the cent. Migration `0053` (Postgres-scoped ALTER; SQLite builds
  Numeric from the models). The Decimal/Float arithmetic that surfaced was fixed
  properly: the compensation display band uses float (a shown estimate), while
  stored payslip gross stays exact Decimal and the run accumulators start at
  `Decimal("0")`. The ~17 other money-NAMED Floats (org-graph budgets, ARR/MRR,
  per-1k-token cost rates, statistical estimates) are deliberately left Float -
  they are analytics/rates, not transactional amounts, and `(18,2)` would
  truncate the token rates. Drift gate green on pg16.
- **`SorObject.deleted` annotation matches its column (4.9).** It was
  `Mapped[bool]` over an `Integer` column that the actuator reads/writes as 0/1;
  the annotation is now `Mapped[int]`, honest to the column and the usage (no
  migration - the column is unchanged).

- **Consistent gated-agent-endpoint error contract (4.5 + 4.11).** finance's
  `/invoices/{id}/match` and `/receivables/{id}/dunning` had the 500 handler but
  no `ValueError -> 404`, so a not-found id returned 500 where nine siblings
  returned 404 - now mapped. healthcare (3) and procurement (4) agent endpoints
  gained the logged, detail-free 500 handler alongside their existing 404 mapping.
  hr's bespoke endpoints already satisfy the contract (get_or_404 + the global
  error envelope), and support `/sla/check` takes no id so it stays a 500-only
  sweep - both documented rather than force-fitted.
- **Intended HTTP status codes are no longer masked as 500.** The shared
  `run_agent_endpoint` wrapper (and the finance/healthcare/procurement handlers)
  caught `Exception` broadly, so an agent that raised e.g. `HTTPException(409)`
  for an invalid state transition surfaced as a 500. Added `except HTTPException:
  raise` ahead of the catch-all everywhere, so a deliberate status propagates
  unchanged (caught by the healthcare triage route test).

- **`financial_amount_logged` is GAAP-inclusive everywhere (4.2).** finance seeded
  this Gate-6 flag for SOX or GAAP; hr and sales seeded it for SOX alone, so a
  GAAP-only financial amount escaped the "was the amount logged?" check in two
  departments. hr and sales converged on finance's GAAP-inclusive standard.
- **Empty compliance-tags mean the same thing in every department (4.3).**
  `compliance_tags=[]` meant "deliberately no tags" in hr/healthcare/engineering
  but was silently replaced with the defaults in the other seven (truthiness, not
  `is None`). Standardised on `is None`: only `None` falls back to the department
  default, `[]` always means no tags. The `explicit_empty_tags` flag is removed.
  No live caller passed `[]` to a converging department, so this closes a latent
  inconsistency rather than changing today's runs.

- **One canonical, always-attributable audit actor (4.10 + M8.8).** Audit-write
  sites derived the actor three ways: `approver_identity(tenant)` (always
  attributes), `tenant.get("email") or tenant.get("name")`, and plain
  `tenant.get("name")` (None for a principal with no name). The same human could
  land in the ledger under two identities, and legal/sales/support agent endpoints
  could record no attributable actor at all. Root cause of the drift: the JWT
  principal never carried an `email` key, so `approver_identity`'s documented
  first branch (`tenant.get("email")`) was dead and it fell through to `user_id`
  while the `name` sites recorded the email. Fixed by adding a real `email` to the
  JWT principal and normalising all 94 remaining sites to `approver_identity`, so
  every audit row attributes to one human-readable identity and never to None.

- **Legal can no longer pass its own lawful-basis audit for free (4.1).** The
  `legal` department — whose entire remit is GDPR/CCPA — hardcoded Gate 6's
  `data_processing_basis_logged` to `True` (`source=None, force=True`), so it was
  the ONE department structurally unable to fail its own lawful-basis check (the
  Gate-6 fix had reached hr/sales/support/healthcare but missed legal when the
  runner was duplicated). It now DERIVES the flag from a real `legal_basis` like
  the rest, and force=True is dropped so a caller value is honoured. All five
  legal agents (contract-review, compliance-audit, litigation, DSAR, IP) now
  supply a genuine Art.6 lawful basis, so real runs pass and a run that omits one
  fails Gate 6 as intended.

### Fixed - schema-truth drift repairs + e2e hang (2026-08-19)

- **`pytest tests/` no longer hangs forever (M9.0):** the e2e `BASE_URL` defaults
  to port 8001 (a sibling project's port); when that server held it, the
  bare-socket reachability probe passed, nothing skipped, and every e2e test
  blocked on a 300s read against the wrong server. `backend_reachable()` now
  requires `/health/live` to return KAEOS's identity payload (foreign server ->
  skip), cached per session; the e2e client gets a 5s connect timeout.
- **Four genuine model/migration drifts repaired** (removed from the drift-gate
  allowlist): `missions.spent_usd` / `mission_steps.cost_usd` now declare the
  `server_default('0')` their migration already carries; the
  `ix_skill_embeddings_hnsw` HNSW index and the `uq_sso_verified_domain` partial
  unique index are now declared on their models (the latter on both dialects, so
  the SQLite test schema keeps the partial semantics). Drift gate: 256 tables, 0
  unaccepted differences on pg16.
- **Three deferred CI gates wired (each fixed first, then proven red-then-green):**
  (1) the scoped **mypy** lane (finance/provenance/compliance) had 5 real errors -
  a `Sequence`-vs-`list` arg, two Optional-key/PK-None money-path types, a
  double-checked-locking false positive, and a demo stand-in - all fixed, lane now
  green and wired into `backend-test`. (2) `validate_domain_agents.py` always
  exited 0; it now exits non-zero on any agent read error / missing tenant / a run
  that validated nothing, and gained an `--offline` mode (no Ollama) wired into the
  seeded Postgres lane. (3) `openapi_surface_snapshot.py` now walks the OpenAPI
  document instead of the internal route table (the old `app.routes` walk saw only
  4 of 673 routes under the pinned FastAPI 0.140), gained a `--check` mode against a
  committed 671-operation baseline, wired into the equivalence job.

### Changed - M1.8 model boilerplate (2026-08-19)

- **Consolidated the 83 identical per-model `_uuid()` helpers** into one canonical
  `app/models/mixins.py::new_uuid`, imported aliased as `_uuid` so every
  `default=_uuid` keeps working; the now-unused `import uuid` is dropped per file.
  Proven byte-identical: a fresh `create_all` on pg16 pg_dumps to the exact same
  DDL as before (only pg_dump's random session nonce differs).
- **Deferred (not a shortcut - a correctness call):** the created_at/updated_at,
  tenant_id and id column mixins. A `mapped_column` mixin cannot sit between two
  model-defined columns, so applying them reorders columns in ~30 tables (the
  DDL-dump gate caught it). That is functionally inert (the drift gate compares by
  name) but diverges `create_all` column order from the frozen `0001` literal DDL,
  which is exactly the "invisible column-ORDER change" M1.8 was gated against. Not
  worth a schema-order divergence for a cosmetic saving; the reusable mixin lives
  in `mixins.py` for opt-in, byte-identical adoption on new/verified models.

### Fixed - MED backlog cleanup batch (2026-08-17)

- **Outbound idempotency (§14):** a duplicate queued write could double-meter /
  double-send — `queue_outbound` now dedups on `(tenant_id, idempotency_key)`
  before insert, backed by a new UNIQUE constraint (migration `0051`, de-dupes
  existing pairs first; Postgres-scoped DDL so SQLite dev keeps it via the model).
- **/org/pulse caching (§03):** the ~38-query pulse computation is wrapped in the
  existing `result_cache` (12s TTL, tenant-keyed) so burst polls collapse to one.
- **Accrual reaper (§20):** a scheduled hourly job books any APPROVED invoice
  missing its `AP_ACCRUAL` journal entry (idempotent), so an approved-but-unaccrued
  invoice no longer sits off-books; heartbeat-tracked like the other reapers.
- **HR candidate rejection (§06):** `/candidates/advance` to REJECTED (an adverse
  action) now runs the EEOC four-fifths checker and requires a documented reason,
  fail-closed — matching the gate the agent path enforces.
- **Orphaned `rule_embeddings` removed (§14):** the reader-with-no-writer model +
  dead semantic-search branch are deleted; the table is dropped in `0051`.
- **Migration-on-Postgres gate hardened:** the new gate caught two real
  Postgres-only bugs in `0051` before merge (a 39-char revision id overflowing
  `alembic_version VARCHAR(32)`, and `ALTER … CONSTRAINT` DDL that SQLite rejects)
  — both fixed and re-validated up→down→up on pgvector/pg16. The enum-label check
  now correctly treats VARCHAR-backed enum columns as no-risk (this codebase
  stores enums as strings, so there is no native-type rejection hazard).
- **Frontend:** a shared `<Field>` (useId-wired label↔input) adopted across
  form-heavy views for a11y, and a 402 needs-plan upgrade toast wired into the
  API error path. Tests added for every fix above (invariants fail if reverted).

### Fixed - three-way-match billed-to-date (2026-08-17)

The cumulative billed-to-date query counted every non-VOIDED prior invoice,
including abandoned DRAFT / DISPUTED ones (the `_NOT_BILLED_TO_DATE` guard was
defined but not applied), so a stale draft could permanently force a legitimate
invoice to EXCEPTION. The query now excludes DRAFT/DISPUTED/VOIDED priors. Locked
with tests: a cumulative over-bill across two live invoices raises EXCEPTION, and
an abandoned DRAFT prior no longer blocks a within-limit invoice.

### Added - Governance Proving Ground + Assurance Score (2026-08-17)

Makes the core claim provable. The north-star safe-autonomy-rate measures how much
ran clean but never proves the gates would STOP a bad action - a tenant could sit
at 99% on gates that block nothing. The Proving Ground fires a versioned battery
of KNOWN-BAD actions through the LIVE gate pipeline and scores how many were
caught; that severity-weighted gate catch-rate is the **Assurance Score**.

- Backend `proving_ground` service: an 11-attack battery spanning finance (SOX
  four-eyes, self-approval), lending (ECOA late notice + prohibited basis, FDCPA
  7-in-7, lending SoD), support (PII redaction), procurement (segregation of
  duties), and the governance kernel (prompt-injection guard, irreversible-DELETE
  and money-moving-UPDATE consequence). Each attack is the inverse of an
  already-tested checker, so a green battery is grounded, not theatre.
- `GET /proving-ground/run` returns the Assurance Score + per-attack catch grid;
  `GET /proving-ground/scenarios` lists the battery.
- CI regression gate (`test_proving_ground`): the battery must be perfect (score
  1.0) - a gate that regresses lets its attack escape and fails the build; a teeth
  test proves the harness detects a neutered gate rather than always reading green.
- A live operator page (`/platform/proving-ground`): an animated firing range
  where known-bad actions are launched at the gate wall and deflected in real
  time, an animated Assurance Score ring, and the per-attack catch grid.
  Reduced-motion respected; verified live at 1280px and 375px (100%, 11/11).

### Added - CI-invariant ratchet (2026-08-17)

Every gap the review found by hand is now a CI-enforced invariant, so it cannot
silently regress (the highest-corroboration theme across the 20 lenses):

- **Migrations proven on Postgres:** a CI step runs the full alembic chain from
  an empty Postgres database (the drift check is now dialect-agnostic and honours
  the lane's Postgres URL instead of always using SQLite) — the validation whose
  absence let native-enum / RLS / pgvector / boolean DDL ship unverified. A new
  enum-label check asserts every model enum member exists in its native Postgres
  type (adding a member without an `ALTER TYPE … ADD VALUE` would otherwise reject
  INSERTs on an upgraded prod DB). Validated locally on pgvector/pg16: 257/257
  tables, 86/86 enum types.
- **Egress firewall:** a test fails the build on any bare `httpx.AsyncClient(` /
  `Client(` outside `core/outbound.py` (SSRF-guarded wrapper), with an explicit
  allowlist for the in-process ASGI transport and constant provider endpoints.
- **Department-capability contract:** a test asserts every compliance tag a
  department declares resolves to a registered checker — the dead-`SLA`-tag class
  of bug (a declared control that silently never runs) now fails CI by construction.
- **Compliance invariants (neuter-the-field):** a parametrized pack proves each
  statutory control still fails closed when its enforcing field is removed/blanked
  (SOX four-eyes, ECOA 30-day, LENDING_SOD, FDCPA Reg F, PII redaction) — a
  control cannot be silently disabled by dropping a field.
- **Query budget:** a per-endpoint statement-count harness pins the hot dashboard
  reads (`/dashboard/health`, `/org/pulse`, workforce departments) so an N+1 or an
  unbounded full-row scan regression fails CI.

### Fixed - 20-lens review remediation, Wave 1 safety fixes (2026-08-17)

A 12-agent verification pass mapped every 20-lens finding to its true state
against the Wave-0 HEAD (most were already closed); this closes the remaining
confirmed-open HIGH safety findings. No schema changes required.

- **DR-safe erasure journal (HIGH):** the deletion journal now also writes to an
  external append-only file sink (`KAEOS_DELETION_JOURNAL_PATH`) outside the DB
  restore boundary, with a replay path — a restore that resurrects PII can be
  re-erased even though it wiped the in-DB journal (file sink is the floor;
  object storage / WORM is the upgrade).
- **Right-to-erasure completeness (HIGH):** `erase_subject` now also anonymises
  customer-authored support ticket content, procurement person fields
  (requested_by / receiver_name / vendor_name) and legal contract counterparty
  — closing the last of the 10-department Art.17 coverage gap.
- **Background-job observability (HIGH):** `/ops/jobs` lists durable jobs and
  requeues a terminal-FAILED one (a human-approved `hitl_resume` that exhausted
  retries was previously invisible and never ran); the scheduler records a
  per-job heartbeat surfaced at `/ops/scheduler` (a job dying every tick was
  invisible while `/health` stayed green); a mission reaper re-drives missions
  left RUNNING by a crashed worker (crash-recovery logic that nothing invoked).
- **Finance governance (HIGH):** the AP agent's dead humanless auto-approve /
  accrual branch (unreachable behind the SOX Gate-1 block) is removed; manual GL
  journal entries now enforce SOX maker-checker four-eyes (a single operator
  could post an unapproved manual JE).
- **Per-recipient approval identity (HIGH):** HITL notifications now mint one
  approval link per resolved recipient carrying that human's real identity as
  the token subject, so a link-based approval can satisfy four-eyes (the sole
  caller previously passed no recipient, so every link carried the constant
  `email-approver` subject that four-eyes rejects).
- **CI honesty gates (HIGH):** a new harvest test runs every module's `__main__`
  self-check under pytest (they were inert — CI never executed them), turning
  ~22 statutory/security invariants into real CI gates; added explicit tests for
  the mission Gate-5b `BLOCKED_ACTUATION` re-gate, the ECOA >30-day
  adverse-action block, and the HIPAA Part-2 consent check (all were untested).
  Fixed the `core/net.py` self-check (it patched the wrong `get_settings`
  binding, so its trusted-proxy assertions never ran).

### Fixed - 20-lens review remediation, Wave 0 (2026-08-17)

A 20-lens autonomous review of the gap-hunt remediation found the safety-critical
tail. Wave 0 (this change) closes it; several fixes shipped as inert
column-absent no-ops and are now activated by migration `0050` so they are real,
not decorative.

- **Egress / SSRF (HIGH):** the tenant-supplied `/pipeline/run` REST connector,
  every dormant per-department connector, and the legacy-ERP bridge now route
  through the SSRF-guarded outbound client (cloud-metadata / private targets
  refused, resolved IP re-vetted at connect time). Host resolution on the
  outbound connect path is now non-blocking, so one tenant's slow DNS can no
  longer stall the event loop for every tenant.
- **Billing / entitlements (CRIT):** checkout creates the metered overage price
  item (overage was silently unbillable) and bills the tenant's real seat count
  (was hardcoded to 1); `invite_user` enforces the seat limit; the paid tier is
  granted only for an active/trialing subscription (an unpaid/incomplete sub no
  longer unlocks it) and revoked on cancel/unpaid; a repeat checkout is refused
  (was double-subscribing); an out-of-order webhook cannot re-grant a cancelled
  tenant (`billing_accounts.last_subscription_event_at` cursor); a managed-cloud
  hard execution-allowance cap (429 past the runaway multiple) is enforced on
  `/skills/{id}/execute`.
- **Governance robustness (HIGH):** `is_high_consequence` now escalates a DELETE
  actuation and a finance money-moving UPDATE regardless of tags (a destructive
  skill contract could otherwise run autonomously); the Compliance and Fairness
  LLM gates route their untrusted context through `prompt_guard` and fail closed
  on injection risk (a prompt-injected ticket could otherwise silence a blocker).
- **Legal hold (HIGH):** an `on_legal_hold` flag on the 24 record/document tables
  a litigation hold targets; `erase_subject`, `purge_tenant` and retention now
  preserve held rows (GDPR Art.17(3)(b)/(e); FRCP 37(e) anti-spoliation) instead
  of destroying evidence under hold.
- **Right-to-erasure completeness (HIGH):** erasure now also tombstones Support,
  Engineering, Operations and Legal person records and the DSAR requestor's own
  identity; tenant-purge blob collection covers finance invoice/receipt/report
  and legal DSAR evidence paths; per-subject unique tombstones avoid UNIQUE
  collisions.
- **Lending (HIGH):** the ECOA 30-day clock is re-anchored to the completed-
  application receipt date (12 CFR 1002.9(a)(1)), not the internal decision date;
  the FDCPA Reg F 7-in-7 call-frequency cap (12 CFR 1006.14(b)) is enforced; a
  new `LENDING_SOD` four-eyes checker blocks a policy-maker from self-approving
  the underwrite the policy authorizes (`lnd_credit_policies.updated_by`).
- **Support (CRIT):** the PII-redaction and SLA-breach compliance checkers now
  actually run on outbound customer content (the default tag set named a
  non-existent `SLA` checker, so the PCI/PII control was dead and PANs/SSNs could
  egress ungated).
- **Finance:** cumulative three-way match counts only APPROVED/PAID prior
  invoices (an abandoned draft no longer forces a real invoice to EXCEPTION).
- **Performance:** the per-tenant LLM router config is memoized (30s TTL,
  invalidate-on-write) off the governed-execution hot path; hot dashboard
  aggregates offloaded.
- **Frontend:** the HR dashboard surfaces a failed fetch instead of silently
  dropping panels (`allSettled` + error state, matching the other six); a shared
  `EmptyState` card replaces the byte-identical per-view copies; Legal/Finance
  raw enums render through `humanize()`.

### Fixed - Gap-hunt remediation (2026-08-16)

A 52-finding adversarial gap-hunt across the 10 departments + platform was
remediated in 48 files, each fix independently verified (unit suite 1094 green,
ruff/bandit clean, frontend build+lint+tests green). Highlights:

- **Governance:** SOX segregation-of-duties is now enforceable (maker/approver
  identities populated + fail-closed four-eyes); mission-driven financial
  write-backs are re-gated against SOX/GAAP at actuation instead of bypassing
  the compliance engine.
- **Lending:** ECOA adverse-action 30-day clock is computed from the decision
  date (was hardcoded, could attest a late notice as timely); cured/paid-off
  loans leave the collections queue; the delinquency queue is bounded and its
  bucket computed live.
- **Healthcare:** the PHI Part 2 / authorization disclosure gate binds the
  encounter's stored SUD codes and the consent store (was trusting caller JSON,
  so consent revocation had no teeth).
- **Privacy:** right-to-erasure now covers Sales, Finance and Healthcare PII
  (was HR + lending only, returning a false "erased" receipt); tenant purge
  collects Legal document blobs; SOAR containment cannot lock out the last admin.
- **HR:** AI screening can no longer autonomously reject a candidate; the
  performance / offboarding / compensation routes run through the 7-gate
  pipeline; the exit interview is recorded even when the model is unavailable.
- **Finance:** invoice accrual / void-reversal now runs on bulk-transition and
  the AP agent (was single-endpoint only, desyncing the ledger); three-way match
  tracks billed-to-date to block split-invoice over-billing; invoice/PO vendor
  identity is reconciled.
- **Support / Sales:** governed support agents now supply legal_basis (was
  failing Gate 6 on every run); the SLA monitor computes breaches live;
  escalations persist an event; sales N+1s batched; the dashboard pipeline
  figure matches analytics.
- **Workforce:** the pack loader warns on undefined capability processes; a
  pack's confidence-floor is applied as an AutonomyPolicy; seed_knowledge and
  deploy_agents are idempotent per-capability; a cross-tenant deployment read is
  closed.
- **Platform:** the ServiceNow sync cursor derives from record timestamps (was
  wall-clock, silently dropping records); outbound write-back idempotency probes
  fail closed across all seven SoR adapters and capture external ids; SKIPPED
  write-backs are requeueable; DLQ / webhook-secret operator surfaces emit audit
  events; VectorStore initializes once per process (was taking ACCESS EXCLUSIVE
  locks on every search/upsert); the embedding model is unified so EMBEDDING_MODEL
  actually drives RAG.
- **Legal / Operations:** a work-order lifecycle state machine + transition UI;
  compliance obligations auto-flag overdue; the DSAR pending count is corrected;
  operations N+1s batched; IP renewal deadlines surfaced.

## [2.0.0] - 2026-08-15 - "Ten Departments, Governed"

The 2.0 line: KAEOS ships **ten governed departments** at full depth, with the
pre-launch gate cleared, the 441-test e2e lane green on real local inference
(qwen2.5-coder:7b, 1h16m), the unit suite at 1053 green, migrations validated
on real Postgres 16, and - for the first time in the repo's recent history -
**every CI lane green** (backend-test, backend-e2e-mock, backend-lint,
security-scan, frontend-build, sbom).

Everything between v1.9.0 and this tag is described in the dated sections
below, which were written as the work landed. The arc, in one paragraph: the
three new regulated departments (Healthcare, Procurement, Banking & Lending)
joined the original seven as full packages with deterministic fail-closed
compliance checkers; a 14-agent audit then drove all ten to depth parity (107
gaps closed, including production-breakers like a missing engineering
migration and a sales audit-gate that failed on every call); the pre-launch
audit fixed 1 critical and 7 high findings (Stripe entitlement sync, HITL
department-scope, PHI-safe ingest, lending erasure, retention sweep, rate-limit
middleware order, default LLM spend ceilings); and the CI repair fixed the test
architecture and three Postgres-only seed bugs that SQLite had been hiding.

### Depth pass: every department audited, then taken to parity

A 14-agent audit of all ten departments and the cross-cutting surfaces found 107
gaps (18 critical). All of them are now closed, with the backend suite grown from
814 to 1043 tests.

**Production-breaking defects.** Three of these would have failed in production:
- **Engineering had no migration at all.** Its six tables existed only via the
  `create_all` baseline, which is refused in production. A deploy following the
  documented `alembic upgrade head` path left every `/engineering/*` endpoint
  permanently returning 500, with a swallowed warning as the only symptom.
  Migration `0045` creates them, plus on-call rotations and CI pipeline runs.
- **Every gated sales agent failed its audit gate.** The runner asserted
  `data_processing_basis_logged=True` without ever setting a `legal_basis`, so
  Gate 6 returned `FAILED_AUDIT` instead of a decision on all six agents. The flag
  is now derived from a real lawful basis, as HR already did. The existing test
  missed it because it only asserted `status_code == 200`, never the body.
- **RBAC rejected the three newest departments.** Scoping or inviting a user into
  Healthcare, Lending or Procurement returned a 400 from a hardcoded seven-slug set,
  while the UI dropdown correctly offered all ten.

**Ungoverned decisions brought under the gate pipeline.** Patent abandonment
(Legal), discount and margin approval (Sales CPQ), and PHI disclosure (Healthcare)
each mutated real state while bypassing compliance, HITL and the audit trail. All
now route through the seven-gate pipeline.

**Agents that ran but changed nothing.** Nine agents across Legal and Operations
ran a full governed LLM call and discarded the result, so every Review, Audit and
Evaluate button left the record untouched. They now persist their decision.

**Fabricated numbers replaced with real ones.** Per-policy SLA metrics were derived
from one unrelated aggregate row plus a hardcoded five-point fudge; vendor risk and
SOC2 status were `getattr` defaults; inspection scores were a three-rung status
lookup. All are now computed from real rows, or honestly reported as absent.

**Reach.** Roughly 90 endpoints added across HR, Legal and Support for models that
were seeded but unreachable; loan servicing and collections built so the advertised
FDCPA controls actually execute; facilities work orders, healthcare agent routes and
procurement sourcing wired to real UI actions. The org-wide health view, Reality
twin, What-If simulator, mission planner and event mesh all cover ten departments
instead of seven. Neural Map labels no longer collide at ten departments, and the
colour palette no longer repeats a hue.

Every migration validated on a real Postgres 16 container, not only SQLite.

### All ten departments visible everywhere + org-graph seeding fix
Two defects meant the three new departments existed in the API but were invisible
in the org-wide surfaces, and the living views rendered a near-empty organisation:
- **`seed_departments()` hardcoded seven departments.** Healthcare, Procurement and
  Banking & Lending had full backends but no `Department` record, so they never
  appeared in the Departments hub, Neural Map, Org Pulse or any cross-department
  rollup. All three are now seeded with their real agent and capability counts and
  the statutory frameworks their gated runners actually enforce.
- **The workforce org-graph was never seeded.** `capabilities`, `department_agents`
  and `deployed_agents` were all empty on a fresh database, so the Neural Map and
  Reality Experience drew an organisation with no agents. A new startup step
  (`app/core/workforce_seed.py`) drives the product's own deterministic deployment
  path - `WorkforceGenerator.generate_department_structure()` then `deploy_agents()`
  - against each synced domain pack. Nothing is fabricated: capabilities, agent
  names, personas and compliance tags come from the pack definitions, so the demo
  organisation is built exactly the way a real tenant's is. Idempotent and
  LLM-free. Result on a fresh database: 10 departments, 45 capabilities, 51 agents,
  31 processes, and a Reality twin of 173 nodes.

### Commercial frontend + futuristic landing page
- **Operator console** (`/platform/operator`, super-admin via `X-Admin-Secret` held
  in session memory only), **public status page** (`/status`, no auth), and
  **white-label branding** (Settings tab + a `BrandingContext` that applies the
  tenant's product name, logo and accent across the shell).
- **Landing page rebuilt** as a living single page: animated neural hero with a
  safe-autonomy ring, the category ladder, all ten governed departments with their
  statutory checker chips, a live seven-gate pipeline, and the honesty contract.
  Respects `prefers-reduced-motion`; no emojis, no em-dashes.

### New department UIs + comprehensive demo data (Healthcare, Lending, Procurement)
- **Premium frontend for the three new departments**, matching the existing
  Finance/Sales view pattern and bound to the real routers: each leads with a
  live overview (rAF-animated ring + count-ups + donut, 20s refresh) and surfaces
  the governance story in plain English - Healthcare renders each PHI disclosure's
  HIPAA minimum-necessary / authorization / 42 CFR Part 2 checks; Lending shows the
  four-fifths fair-lending ratios (and flags adverse impact), ECOA specific-reason
  decisions and adverse-action notices; Procurement shows the four source-to-pay
  controls (spend auth, segregation of duties, three-way match, OFAC) per PO.
  Registered in the department nav; responsive to 375px; SVG icons only.
- **Comprehensive seed data** so every new surface is populated and the governance
  monitors have real spread: Healthcare (8 encounters across acuities, 5 PHI
  disclosures incl. a Part 2 case, consents incl. a revoked one, clinical tasks);
  Lending (14 applications over 4 products/policies with pre-computed underwriting
  decisions + TILA disclosures and ECOA adverse-action notices, protected-class
  distribution that makes the four-fifths monitor detect real adverse impact);
  Procurement (vendors incl. a sanctions-flag demo, requisitions, POs, and goods
  receipts spanning full-match / short-shipment / damaged for the 3-way match).
- Dropped `frame-ancestors` from the SPA `<meta>` CSP (ignored there by browsers;
  enforced via the backend header + `X-Frame-Options`) to clean console noise.

### Commercial + observability backend: operator console, status, metrics store, white-label
- **Super-admin operator console** (`/api/v1/ops/*`, gated by the existing
  ADMIN_SECRET super-admin dependency, fail-closed): cross-tenant `/ops/tenants`,
  per-tenant usage/entitlement/health at `/ops/tenants/{id}`, and platform
  `/ops/overview` (tenant counts, plan distribution, blended safe-autonomy rate -
  null-with-note when there is no activity). Cross-tenant reads go through the
  owner/maintenance session by design, never by dropping tenant filters.
- **Public status page** (`/status`, no auth): db/redis/llm reachability, version,
  uptime. Deliberately does NOT expose the platform safe-autonomy rate - that is a
  business metric and its cross-tenant aggregate is an unindexed scan, so it stays
  on the gated `/ops/overview` (no DoS-amplification on an auth-free endpoint).
- **Time-series metrics store**: `ts_metric_samples` (migration `0043`, RLS) plus a
  leader-guarded hourly rollup that snapshots each active tenant's safe-autonomy
  rate, execution volume, and cost - idempotent per bucket, and a metric with no
  underlying data is never stored as a fabricated 0. `GET /metrics/timeseries`
  returns the stored series so Time Machine reads recorded history, not an on-read
  reconstruction. Interval via `METRICS_ROLLUP_INTERVAL_MINUTES` (default 60).
- **White-label tenant theming**: `brand_tenant_branding` (migration `0044`, RLS) +
  `GET/PUT /branding`. Admin-gated writes with fail-closed validation (hex colors;
  logo_url must be http(s), never a `javascript:`/`data:` URI); reads fall back to
  sane KAEOS defaults so the SPA can theme per tenant.

### Every department to production depth (8+): Healthcare, Lending, Procurement, Engineering
Brought the three thin departments up to the Finance/HR standard and closed
Engineering's one gap. Each built on a disjoint file tree, then adversarially
verified; central migrations/wiring integrated and validated on real Postgres.
- **Healthcare** is now a full department (`app/healthcare/`): patient encounters,
  PHI disclosures, consent records (42 CFR Part 2), and clinical tasks. A PHI
  disclosure is gated by the existing HIPAA minimum-necessary + authorization
  checkers and is refused (never recorded) on a statutory violation or a hard
  governance block. Migration `0041` (RLS on all four `hlth_` tables).
- **Banking-lending** is now a real vertical (`app/lending/`): loan applications,
  underwriting decisions, adverse-action notices, and credit policy. Underwriting
  runs ECOA/Reg B + fair-lending (four-fifths) as real fail-closed gates; adverse
  action carries specific reasons within 30 days. New FAIR_LENDING / TILA / FDCPA
  compliance checkers and a lending domain pack. Migration `0042` (RLS on `lnd_`).
- **Procurement** is promoted to a first-class department (`app/procurement/`): a
  source-to-pay router + service that binds the existing four checkers (3-way
  match, segregation of duties, spend authorization, OFAC) as gates over the
  operations P2P models - no schema duplication.
- **Engineering** gained its missing deterministic compliance checker: SOC2 CC8.1
  change management, ISO-27001 change control, and change-freeze enforcement -
  fail-closed, auto-discovered, and scoped so a normal code review of a red-CI PR
  is advised, not blocked.

### Campaign closeout: finance FX, transport CSP, prompt-injection fences, connectors
Integration of a multi-agent closeout batch, each finding adversarially verified
before landing:
- **Multi-currency general ledger (correctness).** Every journal line now converts
  to the tenant base currency at post time via a new `fin_fx_rates` table, and all
  GL reports (trial balance, income statement, balance sheet, cash-flow) aggregate
  the base-currency amount instead of summing native debit/credit columns - a
  multi-currency tenant was previously adding, say, EUR and USD magnitudes into one
  meaningless total. A reversal now re-converts at the original entry's rate so the
  base amounts offset to exactly zero. New setting `FINANCE_BASE_CURRENCY` (default
  USD); migration `0040_fin_fx_rates` (additive, RLS, inspector-guarded).
- **CRITICAL - Content-Security-Policy blocked the whole app.** The new CSP set
  `default-src 'self'` with no `connect-src`, so the SPA (served on a different port
  than the API) could make no XHR or WebSocket calls at all. `connect-src` now allows
  the cross-origin API and WebSocket (local http/ws in dev, https/wss in prod), with
  `object-src 'none'` added; operators can pin it via `CONTENT_SECURITY_POLICY`.
- **HIGH - prompt-injection fence escape.** Untrusted content wrapped for the LLM
  could emit the literal fence close-marker and inject trusted-channel instructions.
  `wrap_untrusted` now neutralizes embedded markers at the root, protecting chat RAG,
  the debate engine, HR knowledge, and missions in one fix.
- **Write-back connector library + Salesforce idempotency.** Zendesk/Jira/Slack
  outbound adapters; the Salesforce create path gained the idempotency probe the other
  adapters already had, so a lost response cannot duplicate a record.
- **Info-leak fences.** The chat stream, failed-deployment step log, and health
  dependency probes no longer surface raw exception text (DSN/host) to tenants.
- Removed the dead legacy HMAC-token verification path (past its removal date);
  demo-data seeding is now skipped in production-like environments.

### Pre-launch audit: blocking fixes (adversarial attack pass)
An adversarial pre-launch audit attacked the codebase; these blockers are fixed:
- **CRITICAL - SSO open-redirect token theft.** The freshly minted session token
  was handed back in a redirect to an unvalidated `return_to`, so an
  attacker-crafted SSO link would leak the token to their host (pre-auth account
  takeover). `return_to` is now validated: only a site-relative path or an
  allowlisted origin is honored, everything else falls back to the app root.
- **HIGH - four-eyes bypass on vendor payments.** The approve path and the pay
  path derived the actor identity two different ways, so for JWT (human) users
  the segregation-of-duties check never matched and a person could approve then
  pay their own invoice. Both now use the canonical `approver_identity`; proven
  by a route-level integration test (the old isolated unit test had masked it).
- **HIGH - authenticated arbitrary file read.** A caller-supplied `resume_path`
  was opened with no confinement, so an operator could read any file the process
  could (e.g. `.env` secrets) and have the screening echo it back. Reads are now
  confined under a resume base directory (absolute paths and `..` escapes
  rejected), protecting already-stored rows.
- **HIGH - placeholder secrets could boot production.** The config gate accepted
  a shipped `CHANGE_ME...` `SECRET_KEY` (world-known on a public repo, so admin
  JWTs would be forgeable). It now rejects any placeholder secret and requires a
  >=32-char `SECRET_KEY`, and rejects a placeholder/weak `ADMIN_PASSWORD`.
- **MEDIUM - CSV formula injection.** Exported evidence cells starting with
  `= + - @` (tab/CR) are now text-prefixed so a tenant-controlled value cannot
  execute a formula when an auditor opens the file.

### Shipped-milestone review, batch 2 (security + billing + AP integrity)
- **Payment can no longer bypass the ledger.** The manual `PAID` / `PARTIALLY_PAID`
  invoice transitions are removed: paying goes only through `record_vendor_payment`
  (`POST /finance/payments`), which posts the GL settlement, enforces four-eyes,
  the accrual, overpayment, and now the duplicate-flag control. A lifecycle
  transition can no longer zero an invoice balance with no cash movement.
- **TOTP cannot be brute-forced.** A wrong second-factor code at login now counts
  toward the lockout, so an attacker who already has the password cannot grind
  the 6-digit code.
- **A dropped Stripe webhook is retried, not lost.** A known event that could not
  complete (e.g. the subscription webhook arrived before the local billing
  account existed) is left unprocessed and returns 503 so Stripe redelivers it,
  instead of being marked processed and dropped permanently.
- **The AP "Payments Made" tile links to the real General Ledger route.**

### Wave 4: correctness cleanups + fixes from a review of the shipped work
- **Mission money is exact.** `missions.budget_usd/spent_usd` and
  `mission_steps.cost_usd` moved from Float to `Numeric(18,6)` with Decimal
  accumulation, so the budget gate no longer compares binary-float-drifted sums;
  the budget cap is coerced to Decimal at the API boundary (migration `0039`).
- **Mission steps claim atomically.** Step execution now uses
  `SELECT ... FOR UPDATE SKIP LOCKED` on Postgres (in-process fallback on
  SQLite), so two replicas cannot double-execute a step, double-spend, or fire a
  Gate 5b actuation twice.
- **RLS closed on 4 tables.** `confidence_history` and `rule_guardrails` gained
  `tenant_id` + row-level security; `domain_packs` and `marketplace_templates`
  are declared global shared catalogs.
- **The LLM-authored-Python engine is quarantined.** `polymorphic_engine`
  refuses to compile or run generated code unless `ALLOW_POLYMORPHIC_CODEGEN` is
  explicitly enabled (default off); the generated-code dir is gitignored. A dead
  zero-caller engine was removed.
- **Fixes found by reviewing the already-shipped milestones:**
  - **Compliance gate no longer fails open.** A tagged framework with no
    deterministic checker, no PCI raw-card guard, and no LLM screen now emits a
    WARNING (never a silent pass), matching the registry's fail-closed posture;
    the PCI raw-card guard recognizes the `PCI` / `PCI-DSS` / `PCI_DSS` family.
  - **Voiding an invoice reverses its accrual.** Voiding an accrued AP invoice
    now posts an append-only reversal of the `AP_ACCRUAL` entry, so the P&L and
    balance sheet stop overstating expense and the payable (skipped, with a
    warning, if the invoice already took a payment).
  - **3-way match no longer truncates a fractional over-bill.** Invoice quantity
    is compared as Decimal (an unparseable qty fails closed as an exception),
    so billing 10.9 against 10 received can no longer round into tolerance.

### Wave 3: RAG honesty + entitlements/Stripe (open-core + managed cloud)
- **RAG never launders a keyword hit as a semantic score.** When the embedding
  provider is unavailable the router returns hash-seeded pseudo-vectors; the
  search callers no longer treat those as real cosine. `search_skills` returns
  lexical results with `retrieval_mode:"lexical"` and a real bounded lexical
  score (never a fabricated `similarity:0.85`); `semantic_search` and memory
  recall return empty when simulated; and a pseudo-vector is never *persisted*,
  so a later real query cannot match a fake stored one. Added a versioned
  **prompt registry**, **hybrid retrieval** (BM25-lite + reciprocal-rank-fusion
  with an honest fused score), a deterministic **RAG eval** harness (recall@k +
  grounding, CI-runnable), adaptive pgvector dimension, **HNSW ANN indexes**
  (migration `0038`), and a pinned chunker revision.
- **Entitlements + Stripe (open-core + managed cloud).** The platform is fully
  usable self-hosted with billing off (`require_entitlement` is a no-op). In
  managed mode (`KAEOS_MANAGED_CLOUD=true`) `Tenant.plan` gates the managed and
  enterprise features (SSO, SCIM, webhooks, advanced connectors); governed agent
  executions are metered and rated (early-blocked runs are now persisted so
  usage is counted), and an optional **Stripe** bridge (behind an interface,
  no-op without keys) pushes metered+seat usage with signature-verified,
  idempotent webhooks. The webhook processes on the RLS-exempt owner session and
  resolves the tenant from our own records, never the payload. The ROI tile is
  honest: it stays null-with-note unless a per-skill baseline is configured
  (KAEOS never invents a dollar value); the metered-cost tile is a recorded sum,
  not an estimate.

### Wave 2: observability + write-back reliability
- **Reliable system-of-record write-back.** The outbound queue no longer
  head-of-line-blocks: each write is delivered and committed on its own, so one
  dead endpoint fails only its row (it exhausts retries into a terminal `DEAD`
  dead-letter state instead of masquerading as retryable). External idempotency
  keys stop a create whose HTTP response was lost from duplicating on retry;
  connector pulls upsert on a natural key `(tenant, source, external_id)` so a
  re-sync updates the twin instead of inserting a duplicate; a persisted
  incremental cursor + pagination bounds each pull. A **ServiceNow** adapter
  (incidents/tasks/problem/change) lands behind the bidirectional adapter
  interface, routed through Gate 5b. All outbound HTTP uses the SSRF-pinned
  guarded client (migration `0037`).
  - Fixed before merge (found by adversarial review): the scheduled dispatcher
    ran with no tenant context, so under Postgres RLS it matched zero rows and
    write-backs never dispatched — it now uses the RLS-exempt maintenance
    session; the Salesforce branch was using a raw (unpinned, redirect-following)
    HTTP client; and an inbound amount was round-tripping through float.
- **Production observability.** Golden-signal Prometheus metrics (gate pipeline,
  LLM calls, job queue, HITL, leader election) aggregated across the 4 gunicorn
  workers via a multiprocess dir; `/metrics` (opt-in `EXPOSE_METRICS`); request
  correlation IDs threaded through logs; OTLP spans on the gate pipeline. The
  WebSocket layer now fans out across workers over Redis pub/sub (with an
  in-process fallback) so a gate event on one worker reaches a client on
  another — the per-worker subscriber is started on every worker and each send
  is time-bounded so a stalled client cannot block delivery to the rest.

### Wave 1 hardening: security, fairness-to-HITL, real 3-way match
- **Multi-worker session security.** JWT revocation (logout) and login lockout
  are now backed by Redis so a logout or lockout is seen by every worker (prod
  runs 4), with an in-process fallback for single-instance dev. Revocation is
  enforced at every async auth boundary (`get_current_user`, tenant middleware,
  the WebSocket handshake) via `is_jti_revoked`.
- **TOTP replay is blocked.** A one-time code's time-step is consumed with an
  atomic conditional UPDATE, so a captured code cannot be replayed within its
  window and two concurrent submits cannot both win (migration `0036`,
  `user_mfa.last_used_step`).
- **Per-tenant envelope encryption.** At-rest secrets (MFA TOTP secrets, SSO
  client secrets, connector credentials) are encrypted under a per-tenant data
  key wrapped by the master key, so one key leak no longer decrypts every tenant
  and deleting a tenant crypto-shreds its secrets (`tenant_data_keys`).
- **SSO domain-ownership challenge.** A tenant must prove it controls an email
  domain (a DNS TXT record `_kaeos-challenge.<domain>`) before that domain
  routes SSO logins; an unverified or squatted claim is inert, and a verified
  domain cannot be taken over. Login discovery no longer 500s on a duplicate.
- **SSRF connect-time pinning + trusted-proxy IP** on outbound calls and the
  per-tenant IP allowlist / audit trail.
- **Fairness blocks reach a human.** A fairness BLOCK (and the mission
  equivalent) now routes into the real HITL approval queue instead of
  dead-ending, and approval clears the finding on resume.
- **Real deterministic 3-way match.** Ops vendor identity is unified onto the
  single `fin_vendors` master (FK), PO line items carry quantity + unit price,
  and the invoice->PO->receipt chain is linked. A deterministic matcher
  (`invoice_qty <= min(po, received)`, overcharge-only price block) decides the
  status; the LLM only triages genuine exceptions and can never flip it. Payment
  is refused on an EXCEPTION match unless a distinct human override is recorded,
  and the seed shows a genuine matched invoice and a genuine exception (no more
  hardcoded MATCHED against a non-existent PO).

### Premium frontend sprint
- **Shared UI foundation** (`components/shared/`): `<TableCard>` encodes the
  overflow-hidden > overflow-x-auto > min-width pattern ONCE so wide tables
  scroll instead of clipping their rightmost columns on mobile/tablet (the
  defect was ~30 hand-rolled tables split between clipping and scrolling
  wrappers); `<Ring>`/`<StatCard>`/`<MiniDonut>` add rAF-tweened, reduced-motion-
  aware live KPI visuals; `prefersReducedMotion()` is now exported from CountUp.
- **Department views migrated** onto the foundation (Finance, Legal, Engineering,
  Workforce, Infrastructure, DepartmentDetail, EvolutionStudio,
  SkillContractViewer) - tables scroll cleanly at 375/768/1280, grids reflow.
- **Two new premium surfaces** wired into the shell: **Compliance Checker Studio**
  (`/platform/compliance-checker`) - the framework catalog grouped by department
  plus a live pass/block/advisory/UNBACKED runner over `/compliance/check`; and
  the **General Ledger Workspace** (`/departments/finance/gl`) - a tabbed hub
  (Journal, Trial Balance, P&L, Balance Sheet, Periods, Payments) over the new
  finance endpoints, with human-readable money and live figures.

### Department-as-a-Service: deterministic compliance expertise
- **A statutory checker spine, fail-closed** (`app/compliance/`). KAEOS is
  Department-as-a-Service, and each department's real expertise is a
  deterministic statutory checker, not an LLM guess. A framework->checker
  registry judges each `compliance_tag` by statute; a tag with **no** backing
  checker returns `UNBACKED` (blocking) instead of silently passing, closing the
  hole where an unrecognized compliance tag sailed through Gate 1.
  `ComplianceEngine.check_before_execution` now runs the deterministic checker
  first and only falls back to a labeled LLM screen where none exists.
  `GET /compliance/frameworks` and `POST /compliance/check` expose it.
- **27 deterministic checkers across 9 departments**, each pure and unit-tested,
  built and then adversarially hardened (false-PASS/false-BLOCK defects found by
  a reviewer pass and fixed with regression tests):
  HR (EEOC four-fifths, FLSA overtime, I-9), Finance (SOX segregation-of-duties),
  Lending/banking (ECOA/Reg B adverse-action), Legal (conflict of interest,
  legal hold, retention, contract clauses), Healthcare (HIPAA minimum-necessary,
  authorization with 164.512 permitted-disclosure carve-outs, Safe-Harbor
  de-identification, 42 CFR Part 2), Procurement (deterministic 3-way match,
  segregation of duties, spend authorization, OFAC sanctions), CRM/Sales
  (GDPR lawful basis, CCPA, TCPA, DSAR deadlines), Support (PAN redaction via
  sliding-window Luhn, SSN, call-recording consent), Operations (SOX ITGC change
  management, incident postmortem, backup retention).

### Trust artifacts (10/10 hardening, Phase 1 completion + Phase 2 start + Phase 3 keystone)
- **Vendor payments reach the ledger, on accrual basis.** `POST /finance/payments`
  is the first P2P money event wired end to end: the invoice must be APPROVED
  with a recorded approver, the payer may not be that approver (four-eyes),
  overpayment is refused, and the Payment row + invoice balance + journal
  entry + account balances + signed provenance event land in ONE commit
  through the GL keystone. `Payment.journal_entry_id` existed since the schema
  was written; this is the first code to set it.
- **Accrual accounting: the liability is booked when the invoice is approved.**
  Approving an AP invoice now accrues it (`accrue_invoice`: DR expense /
  CR accounts-payable for the full amount) so the P&L and balance sheet reflect
  approved-but-unpaid invoices, and a payment settles the payable (DR
  accounts-payable / CR cash) instead of expensing cash. Accrual is idempotent
  (each invoice books once, guarded by its `AP_ACCRUAL` entry) and is retried
  at payment time for invoices approved before the hook existed, so the ledger
  is correct regardless of history. Wired into the invoice-approval transition
  (`POST /finance/invoices/{id}/transition` -> APPROVED).
- **Financial statements derive from the ledger.** `GET /finance/gl/income-statement`
  (P&L: revenue - expenses = net income, inception-to-date or bounded by
  period_start/period_end) and `GET /finance/gl/balance-sheet` (assets,
  liabilities, equity, as-of a date). Both aggregate POSTED journal lines and
  sign each account by its TYPE - not the mutable `normal_balance` string - so
  a mis-seeded account can never flip a P&L or unbalance the sheet.
  Current-period earnings close into equity so the balance sheet always
  balances (Assets = Liabilities + Equity) without formal period-close entries.
- **Fiscal period lock.** Closing a period (`POST /finance/gl/periods/close`,
  admin-only) refuses back-dated postings into a reported month - the GL
  keystone checks `fin_fiscal_periods` on every post and raises
  `PeriodClosedError`. Absence of a row means OPEN, so months need not be
  pre-created; reopen (`.../periods/reopen`) restores posting for corrections.
  Migration `0035`. Completes Phase 3.1.
- **Embeddings obey the same governance as every other model call.** The
  Polystore embedded rule text via a direct litellm call with a hardcoded
  OpenAI model - bypassing the data-residency filter (a local-only tenant's
  rule text still went to the cloud), cost metering, tenant BYOK and the
  local-Ollama fallback. Both sites now route through `LLMRouter.embed`.
- **AI system inventory + model cards** (`GET /governance/ai-inventory`):
  the EU-AI-Act-shaped answer to "which AI systems run here, on what models,
  with what oversight" - derived from the tenant's live tier-to-model
  routing, probe-measured confidence ceilings (unprobed reports unknown, not
  flattering), and real oversight counts, with code references a reviewer
  can check. An inventory, not legal advice, and it says so.
- **The General Ledger posts for real.** `JournalEntry`/`JournalLine`/
  `ChartOfAccount` were display-only schemas: nothing ever posted, balances
  never moved, and an unbalanced entry would have been accepted. The new
  posting keystone (`app/finance/services/gl.py`) is the only write path:
  fail-closed double entry (sum of debits must equal sum of credits, Decimal
  cents, exactly one positive side per line, active tenant-scoped accounts
  only - violations post NOTHING), race-safe sequential entry numbers,
  account balances moved by normal-balance convention in the same
  transaction as the entry, and a signed provenance-ledger event landing
  atomically with the posting. Corrections are append-only reversals (mirror
  entries), and the trial balance (`GET /finance/gl/trial-balance`) derives
  from POSTED lines - the ledger is the source of truth, with cached-balance
  drift cross-checked and reported. New endpoints:
  `POST /finance/gl/journal-entries`, `.../{id}/reverse`,
  `GET /finance/gl/journal-entries`.
- **The security audit trail is tamper-evident with a durable fallback.**
  Every `SecurityAuditLog` row is HMAC-signed at write time (a DB-level edit
  is detectable by `GET /security/audit-log/verify`), and the scheduler
  anchors windowed per-tenant checkpoints (count + digest) into the signed
  provenance ledger every 12h, so deletions surface too - windowed rather
  than since-genesis because the opt-in 730-day retention class must not
  read as tampering. A failed DB write now lands the signed event in a local
  JSONL fallback sink instead of vanishing into a warning log. On Postgres,
  migration `0034` revokes UPDATE/DELETE from the app role.
- **TrustedHost + browser-hardening headers.** Host-header validation
  (`ALLOWED_HOSTS`, permissive in dev, real hostnames in prod) plus nosniff,
  X-Frame-Options DENY, Referrer-Policy no-referrer, and HSTS outside
  DEV_MODE, on every response.
- **Fairness Gate 2 got real statistics.** When cohort outcome counts are
  supplied, the gate runs the EEOC four-fifths selection-rate test with a
  two-proportion significance check (stdlib math, deterministic, the cohort
  snapshot persisted in the audit log) - measured disparity, not model
  opinion, and the LLM is not consulted at all. Thin samples report as
  advisory instead of hard-blocking on noise. Without cohort data the LLM
  screen still runs, and its rationale is now labeled "[LLM screening - not
  a statistical test]" in every audit record.
- **Maker-checker on rules.** Every rule - typed by an operator, bulk-imported,
  or synthesized by the regulatory engine from pasted directive text - now
  lands NON-executable with its maker recorded (`rules.authored_by`, migration
  `0033`), and starts steering governed decisions only after a different
  authenticated identity validates it. The regulatory engine's LLM
  interpretation used to go live instantly with `is_executable=True`. The
  validate endpoint enforces four-eyes against the AUTHENTICATED principal
  (client-supplied validator text is display metadata, not identity - it used
  to be recorded verbatim, letting any caller attribute a validation to
  someone else), and the checker's approval is what authorizes execution;
  evidence confidence keeps its own job at the runtime confidence gate. The
  old `scalar >= 0.60` executability shortcut conflated the two in both
  directions: un-reviewed rules auto-armed at creation while a human
  validation could fail to authorize anything.
- **The provenance ledger is one signed, verifiable scheme.** Five writers used
  to put five incompatible values in the same `chain_hash` column (two
  different sha256 payload shapes, a sha3-512 chained to the newest row by
  wall clock across all tenants, a hash of a timestamp string, and a random
  `uuid4()`), so the verify endpoint reported cleanly created rules as
  "TAMPERED". Every writer now routes through one writer
  (`app/services/provenance.py`): HMAC-SHA256 signed (a database-only attacker
  cannot recompute a valid chain), explicit parent pointers, per-tenant
  chains (RLS-compatible), and appends serialized by database uniqueness - a
  concurrent append cannot fork a chain on any worker count, no locks
  involved. The verifier recomputes end-to-end and is honest about history:
  pre-unification rows report as `legacy`, never as tampering. New
  `/provenance/stream/verify` covers the subjectless event stream the old
  code had no verifier for. Postgres deployments revoke UPDATE/DELETE on the
  table from the app role (migration `0032`), making append-only a database
  guarantee instead of a convention. The "quantum ledger" facade delegates to
  the same writer, closing its timestamp-derived-parent fork bug.
- **One gated execution path.** `/skills/{id}/execute` (which the MCP
  `execute_skill` tool forwards to) ran a partial inline pipeline that
  skipped Gate 2 (Fairness) and Gate 4 (Debate); the HITL resume re-entered
  at Gate 5 only, skipping fairness, audit and governed actuation on exactly
  the executions a human had just approved. Both now run
  `AgentExecutor.execute_skill` - the same pipeline missions and the domain
  agents use - and the pipeline itself is restructured so the pre-approved
  shortcut and the normal flow share one post-HITL body and cannot drift
  apart. Debate is skipped for human-approved resumes (its strongest outcome
  is "escalate to a human", and a human has already ruled), approved
  actuations are attributed to the approver, and a resume blocked at a
  statutory gate finalizes the execution row instead of leaving it RUNNING
  forever. A regression test locks the route to the pipeline.
- **Approved work survives a crash.** The resume after a human approval was a
  fire-and-forget task: a worker dying between "approved" and "completed"
  lost the run while the row said RUNNING forever. Every approval now
  enqueues a durable `hitl_resume` job atomically with the approval itself
  (same transaction - no crash window), processed by the existing
  leader-guarded job queue with retry and backoff. The resume is idempotent
  on execution_id, so the normal in-process resume makes the backstop a
  no-op, and a crashed one is recovered within minutes.

### Security / Integrity (10/10 hardening, Phase 0)
- **Approving a paused execution now actually runs it.** `POST /skills/hitl/{id}/approve`
  used to stamp `SUCCESS_CLEAN` unconditionally and only resumed the skill if a
  gate-cache record happened to survive - a human could "approve" work that then
  never executed while the ledger said it completed cleanly. Every approval now
  routes through `hitl_manager.resolve_hitl` (the same path as the email-link
  approver), the response is `RESUMING`, and the final status is stamped by the
  executor when the resumed run completes. Approving a finished execution is a
  409. An approval carrying a correction still records the Foundry training
  example, and the resumed run finalizes as `SUCCESS_WITH_EDIT`.
- **Rejections decided via the email link now leave the queue.** `resolve_hitl`
  finalizes the execution row (`HUMAN_OVERRIDDEN`, completed timestamp) on
  reject, so a rejection decided from a notification link no longer sits in the
  pending queue forever.
- **The direct actuation API is gated.** `POST /actuation/execute` was the one
  execution path with no gate at all: one operator API call could delete data or
  move money. High-consequence writes (the shared `is_high_consequence` rule -
  payments, deletions, terminations, and every DELETE operation) now pause in
  the HITL queue and apply only after human approval, fail-closed, attributed to
  the approver, through the same resume path as every other approval.
- **Tenant-scoped business keys are no longer globally unique.** `worker_id`,
  employee/contact emails, invoice/journal/expense/finding/PO/ticket numbers,
  SOX control codes, KB slugs, department slugs and `skill_id` carried a global
  `unique=True`, so tenant B could not create `INV-001` - or seed the standard
  skill catalog - once tenant A had (cross-tenant collision and denial of
  service). All 16 keys are now composite `(tenant_id, key)` (migration `0031`),
  and the skill lookups/joins that relied on global uniqueness are tenant-scoped
  (workforce deploy idempotency, workforce analytics join, predictive-ops intent
  execution - which also no longer leaks every tenant's skill catalog into the
  intent-analysis prompt).
- **Honesty relabel sweep.** The docs no longer claim writes KAEOS cannot make:
  external write-back is scoped to Salesforce + generic REST (the other adapters
  are ingestion-only and say so), the AP agent no longer feeds the model a
  hardcoded `Receipt Status: CONFIRMED` for receipts it does not track (the
  pack process is now "Invoice PO Matching"), Gate 2 is described as
  LLM-assisted bias screening rather than a statutory EEOC test, and
  KNOWN_LIMITATIONS gains the two entries the review said were missing:
  write-back scope and the industry-vertical depth gap.

### Added
- **The intelligence report is delivered as it is written.** Caching removed the
  wait on every request after the first, but somebody still pays it the first
  time an org's numbers change, and half a minute of spinner is the part that
  reads as broken. `GET /benchmark/intelligence-report/stream` sends the report
  over SSE as the model writes it. Measured on the local model with a
  report-shaped prompt: first content at 0.39 s against 26.2 s for the whole
  generation. It shares the blocking endpoint's cache and fingerprint, so a
  cached report arrives whole and instantly on the first event, and a freshly
  streamed one is stored for the blocking endpoint to reuse. The existing
  non-streaming route is unchanged and remains the contract for API clients.
- **`LLMRouter.stream_complete()`**, which mirrors `complete()`'s orchestration
  rather than calling past it: the budget gate still runs before a model is
  chosen, the degraded tier still applies, the data-residency filter still
  strips cloud models, and the call is still metered into `CostEvent` (usage is
  requested on the final chunk, so a streamed call cannot escape the cost
  ledger). Both paths now share one `_prepare_call`, because the PII scrub and
  residency rules are security controls and two copies of them would eventually
  disagree. Fallback deliberately differs: once a delta has reached the client
  it is on screen, so another model is tried only while nothing has been
  emitted, never mid-stream.

### Fixed
- **The copilot's "streaming" was a typewriter animation over a finished
  answer.** `/chat/stream` awaited the entire completion and then replayed it
  word by word on a 30 ms timer, so the reader waited for the whole generation
  and then waited again for the replay, adding roughly 15 s to a 500-word
  answer. It now streams real deltas as the model produces them.

### Performance
Measured against the dev database, not estimated.

**Sweeping the whole read surface (222 GET endpoints) takes 1.9 s where it took
104.7 s.** Profiled in-process before and after, same database, same tenant.
Total SQL statements across the sweep fell from 668 to 541. Nothing was traded
away for it: every payload below is byte-identical to what it was, and where a
field was dropped it was one no surface rendered.

- **Analyses are cached against their inputs, not against a clock.** The three
  slowest reads spent 105 s of a 105 s sweep turning a handful of numbers into
  an LLM-written analysis. They now go through a content-addressed cache: the
  key is a fingerprint of every input the result depends on, so a change in the
  org changes the key and the analysis is regenerated. A stale answer is not
  possible, only a miss. Repeat requests: 105.4 s to 0.018 s, responses
  byte-identical.
- **The expensive analyses are computed before anyone asks for them.** A
  leader-guarded scheduled job warms the two benchmark analyses every 30
  minutes, calling the same builders the endpoints call, so the first user
  request is already warm: 75 s of waiting became 0.049 s. A pass where the org
  numbers have not moved costs nothing, because the cache already answers.
- **`/neural/world` issues 13 queries where it issued 46**, by fetching each
  entity type once across all departments instead of once per department.
  Verified identical: 138 nodes and 181 edges, same hash.
- **`/org/pulse` 50 to 33 and `/org/digest` 54 to 36.** Most of the saving was
  work whose results were discarded: the seven domain analytics services each
  computed chart series that these two endpoints never return. They now say so.
  The rest were pairs of queries scanning the same rows twice, merged into one
  pass with conditional aggregates, and two SLA sweeps over tables whose models
  carry no timestamp column, so they could only ever return nothing.
- **The SLA sweep filters in SQL.** It read up to 2000 rows per workflow table
  per pulse and discarded the non-breaching ones in Python; it now selects only
  breaching rows, and only the columns the breach record is built from.
- **Oversized payloads trimmed to what the UI reads**, verified by grepping the
  frontend and by the compiler: `/agents/blueprints` ships 61 KB instead of
  92 KB, having stopped sending four heavy JSON columns that only the detail
  route renders.

### Fixed
- **Two rollups in the executive digest had never worked.** `CostEvent` has no
  `created_at` column (it is `timestamp`) and `Incident` has none either (it is
  `detected_at`), so both queries raised `AttributeError` into a handler that
  logged and moved on. The digest therefore reported model spend as "not
  metered" and incidents as zero, in every digest ever sent, rather than
  reporting an error. Both now return real figures. A sweep across all 204
  mapped model classes confirms no other query references a column its model
  does not have.

- **`GET /extraction/candidates` went from 67 s to 25 s** against the real local
  model, returning the same seven mined rules. Three causes, in order of impact:
  - It made one rule-mining call per domain **sequentially**, so the request
    cost the sum of seven local-model calls. They now run concurrently. Nothing
    in that loop shares the request's database session, which is what makes
    `gather` safe here and not elsewhere in this codebase.
  - Concurrency is **bounded to three**, which is faster than an unbounded
    fan-out, not merely politer. Measured on this box for seven prompts:
    sequential 59.4 s, two at a time 31.9 s, three at a time 22.4 s, all seven
    at once 24.5 s. Past three the GPU thrashes. The bound also stops one
    endpoint queueing the governance gates and the copilot behind it, since
    they share the same model.
  - Every signal reached the prompt as a **Python dict repr**, because the
    caller sent `payload` and the miner read `clean_payload`, so the fallback
    stringified the whole record including its id. That was about a third of
    the prompt spent on syntax the model had to ignore. The miner now accepts
    either key and emits the payload text only.
- **A rule-mining prompt now carries at most 25 signals.** One domain had 65 and
  dominated the request; a rule generalized from 25 examples is the same rule.
  The reported `confidence_basis` still counts every instance, so the evidence
  claim did not shrink with the prompt.

- **`/neural/world` issues 36 queries instead of 49**, with byte-identical
  output. Two of the per-department queries were removable: the department's
  integration mappings were fetched twice with the same WHERE and different
  projections, and the tenant's connector list, which does not depend on the
  department at all, was re-scanned once per department. The org-wide view now
  fetches connectors once and passes them in; the single-department graph still
  loads them itself. The per-department skill scan is also capped, since task
  labels are de-duplicated only after loading.
- **Unbounded list reads are now bounded**, with the shape of each cap chosen to
  fit what the endpoint means:
  - `GET /skills/hitl/pending` is the hottest read in the product (the app shell
    polls it every 30 seconds for every signed-in user on every page) and
    PENDING_HITL is a queue, not a window, so a stalled approver grew it
    forever. Capped newest-first, and it no longer ships each execution's full
    `context` payload, which nothing rendered.
  - `GET /genome/state` counted weekly buckets by loading every execution row,
    including their JSON. It now aggregates in SQL, grouped by day and folded
    into ISO weeks. A row limit was the wrong tool here: it would have silently
    truncated the timeline being drawn. Verified to produce an identical timeline.
  - `GET /skills` aggregates `total`, `total_executions` and
    `avg_success_rate` in SQL over the whole filtered set while returning a
    bounded page. Computing them from the page instead would have made `total`
    mean "page size" and skewed the execution-weighted success rate.
  - `GET /redteam/scans/recent` is bounded by a 30-day window rather than a row
    limit, because its rows are grouped per skill and a row cap would drop whole
    skills from the aggregate, changing the answer instead of trimming it.
  - Caps added to the provenance chain, rule confidence history, rule versions,
    extraction candidates (which also bounded an LLM prompt that grew with the
    signal firehose), and the three advanced-capability lists, which fan out over
    a JSON event array inside each row and so are now capped on both axes.
  - `GET /reality/learning` loaded every shock outcome to display twenty of them;
    the per-decision averages are now computed in SQL over the full history and
    the feed reads only what it shows.
- **`GET /provenance/{rule_id}` accepted a tenant id and never applied it**, so
  any rule's chain was readable across tenants. It now filters on it, and returns
  an explicit field list rather than raw ORM rows, which had been auto-exposing
  `actor_hash` and `evidence_ids` and would ship any column added later.

- **Password hashing no longer blocks the event loop.** bcrypt is deliberately
  expensive and entirely CPU-bound: `verify` measured 207 ms and `hash` 224 ms,
  and both ran directly on the single event-loop thread. Every login therefore
  stalled every other in-flight request in the process, including gate
  pipelines, WebSocket traffic and running LLM calls, so concurrent logins
  serialized. Both helpers are now async and offloaded with `asyncio.to_thread`,
  the pattern already used elsewhere in the tree. Eight concurrent logins now
  complete in 0.44 s wall clock against roughly 1.66 s serialized.
- **The at-rest encryption key is derived once per process, not per call.**
  `_fernet()` ran a 200,000-iteration PBKDF2 derivation (~36 ms, on the loop) on
  every encrypt and decrypt, although its salt and iteration count are module
  constants and its secret comes from the already-cached settings, so the result
  was invariant. `LLMRouter.for_tenant()` calls it once per configured tier and
  runs several times per governed decision, which cost a BYOK tenant close to a
  second of blocked loop per decision, none of it inference. Now `lru_cache`d.
- **Three relationships were eagerly loaded and never read.** `Rule.guardrails`,
  `Rule.provenance_entries` and `Skill.executions` carried `lazy="selectin"`,
  so every `select(Rule)` issued three queries and every `select(Skill)` two,
  across roughly 68 call sites; `Skill.executions` also hydrated each
  execution's `context` and `reasoning_chain` JSON, and `provenance_entries`
  eagerly loaded an append-only ledger that grows without bound. Confirmed by
  search that no code reads any of the three as an ORM attribute. Both selects
  now issue exactly one query.

### Security
Eight trust-boundary defects, each a request-supplied value reaching a
filesystem path, an outbound host, an LLM prompt or a governance ledger without
being constrained first. New `tests/test_trust_boundary.py` pins all of them.

- **A pipeline run could read any file the process could, and post it off-box.**
  `POST /pipeline/run` passes `connector_config` straight to the CSV connector,
  which called `open()` on the caller's `file_path` with no confinement, while
  the pipeline's webhook destination will POST whatever is extracted to a
  caller-supplied URL. One operator-role request could therefore ship `.env`
  (signing key, admin secret, database URL) to an arbitrary endpoint. The
  connector now resolves `file_path` under a fixed input directory, rejecting
  absolute paths and `..` escapes, exactly as `LocalFileDestination` already did
  on the write side.
- **Governance ledgers recorded a client-supplied actor.** `approver_identity()`
  exists and states the rule outright: the recorded approver must come from the
  authenticated principal, never a request field. Four paths ignored it, the
  worst being the fairness override, where the record of *who cleared a bias
  block* was whatever string the caller typed. Blueprint creation, blueprint
  approval, the fairness override and schema-mapping confirmation now all derive
  the actor from the authenticated principal, and the fields are gone from the
  schemas so they cannot be reintroduced.
- **Three audit reads and one report crossed the tenant boundary.**
  `GET /rules/{id}/provenance`, `/rules/{id}/history` and
  `/rules/{id}/versions` filtered on the rule id alone, returning another
  tenant's reasoning, confidence deltas and chain hashes; `GET
  /reports/compliance` counted rules and audit rows install-wide, so one
  customer's SOX/GDPR/HIPAA posture was computed from everyone's data. All four
  are now scoped in the query rather than relying on Postgres RLS, which does
  not protect the SQLite path. `confidence_history` has no tenant column, so it
  is scoped through its parent rule.
- **One tenant could confirm another's schema mapping.** `confirm_mapping`
  selected on the mapping id with no tenant filter while its sibling
  `get_mappings` scoped correctly. Since ingestion trusts a confirmed mapping's
  `target_entity`/`target_field` to route records, this could redirect another
  tenant's incoming data. Now tenant-scoped.
- **The copilot's prompt-injection guard could be skipped by relabelling a
  turn.** The client submits the whole transcript and `neutralize()` ran only
  when `role == "user"`, but `role` was an unconstrained string, so a turn
  labelled `system` passed through unneutralised and rendered directly above
  `ASSISTANT:`. Every turn is now neutralised and `role` is constrained to
  `user`/`assistant`.
- **A synthesized tool name could escape its directory.** `missing_integration`
  became a filename under the dynamic MCP tool directory and was interpolated
  into the code-generation prompt; it is now constrained to a bare module name.
- **Three request-supplied URLs reached `httpx` unchecked** (connector config,
  event-bus webhooks, pipeline webhook destination), making the cloud metadata
  endpoint reachable, and on the connector sync path the response was returned
  to the tenant as Signal rows. A single shared guard now rejects non-HTTP
  schemes and the metadata address everywhere, and private or loopback targets
  outside `DEV_MODE`, so local development and the test suite still work.

### Fixed
- **Internal error strings no longer reach API clients.** Four routes
  (`agent_factory`, `federated`, `polymorphic`, `advanced`) caught every
  exception and returned its text in a 500 body, leaking file paths and stack
  context. They now let the failure reach the new catch-all, which logs the
  full traceback server-side and returns only a request id.
- **Department dashboards no longer overflow on a phone.** Every stat and KPI
  grid used a fixed `grid-cols-3/4/5/6` with no breakpoint, so the columns ran
  off-screen below tablet width. All 64 across the pages and views now stack
  down a responsive ladder (1 or 2 up on mobile, full width on desktop).
  Verified at 375px with no horizontal scroll on the Finance dashboard.
- **A failed role, department or knowledge change now says so.** Bring-Your-Own-
  Knowledge ingestion and the User Management role/department mutations caught
  their errors into `console.error` and showed the user nothing, so a failure
  read as a silent no-op. Each now surfaces a visible error notice.
- **Background runs no longer bleed into a human's gate trace.** Gate events are
  broadcast tenant-wide, so the scheduler, precog and the autonomy governor could
  interleave their gates into a trace someone was reading as the verdict on the
  action they had just taken. Executions now carry the actor that triggered them
  (published from the same middleware hook that publishes the tenant, so no route
  changed), and the trace ignores anything no person started.
- **A dial the governor tunes is now one a human can take back.** The Autonomy
  Dial listed seven hardcoded domains, but the governor derives a domain from the
  executed skill's department and creates dials for whatever it finds. Dials for
  `marketing`, `customer_support`, `human_resources` and `general` were therefore
  enforced by Gate 3 while being invisible in the UI and rejected by the update
  endpoint, so "human override wins" did not hold for them. Both the listing and
  the update now derive the domain set from real policies and real skill
  departments, so the governed set and the overridable set are the same set.
- **A compliance control cited a dead file as its evidence.** Control AU-2
  ("Hash-chained decision provenance", SOC2 CC7.3 / SOX 302+404) claimed
  IMPLEMENTED while pointing at `governance_engine.py` - an ABAC module with no
  hash chain, called by nothing. The chain is implemented by `quantum_ledger.py`
  and written by the actuator; AU-2 now cites those plus its test. A new
  `test_control_evidence_paths.py` fails the build if any control cites a path
  that does not resolve, or if an IMPLEMENTED control cites nothing at all.

### Added
- **A single catch-all for uncaught exceptions.** The API had no handler beyond
  FastAPI's default, so an unhandled error returned an inconsistent bare 500.
  One handler now logs the full traceback and returns a stable envelope
  (`{"error": {"code, message, request_id}}`) carrying the request id, so
  support can correlate a user's 500 with the server log without the user
  seeing internals. Deliberate `HTTPException`s and validation errors keep their
  existing contract, which the frontend and e2e suite depend on.
- **The Enterprise Genome and Evolution Studio views are reachable again.** Both
  read live backend state (`/genome/state`, `/evolution/state`) but had lost
  their mount in an earlier refactor and rendered nowhere. They now sit as tabs
  in the Decisions view beside the evolution timeline. Verified live: genome
  traits and a six-snapshot fitness timeline; current-vs-simulated fitness with
  an eight-dimension matrix.
- **The autonomy governor now records every dial it moves, and the dial says who
  moved it.** The governor adjusts each domain's confidence threshold from the
  measured safe-autonomy-rate every six hours, but recorded nothing: a human
  moving the dial wrote a `CONFIG_CHANGE` audit row while the machine moving it
  wrote none, so the one actor that can widen its own authority was the one
  leaving no trace. Each change now writes the same audit event shape, attributed
  to `autonomy-governor`, carrying the evidence behind it (previous and new
  threshold, direction, measured rate, override/failure fraction, sample count,
  window, and a plain-English reason). The Settings dial reads `default` /
  `set by you` / `auto-tuned` instead of collapsing the last two into "custom".
- **The 7-gate trace is now visible in HR and Finance.** The runtime already
  broadcast a `gate_event` per gate transition, and the live trace component
  that renders it was mounted in five department views but not in the two where
  the gates matter most: HR candidate screening (the fairness gate's whole
  reason to exist) and Finance AP/AR runs (the always-HITL, money-moving class).
  Both previously showed only a one-line verdict. Subscribes to events already
  on the wire, so no new endpoint and no polling.
- **Responsive app shell.** Below the `md` breakpoint the sidebar becomes an
  off-canvas drawer behind a scrim, opened from a top-bar control and dismissed
  by the scrim or by navigating; at `md`+ the layout is unchanged. HITL approval
  is the daily human touchpoint, so it now works from a phone. Verified at 375 /
  768 / 852 with no horizontal overflow on the primary surfaces.

### Removed
- **Five backend engines and three frontend components that nothing referenced**
  (`benchmark`, `impact_engine`, `learning_engine`, `governance_engine`,
  `scorecard_engine`; `ExecutionDetailView`, `FeedbackCapture`,
  `ConnectorCredentialsModal`). `governance_engine` was also the only fail-open
  gate in the tree, so removing it drops a governance asterisk rather than any
  coverage. `learning_engine` fed an injection point nothing ever injected, so
  its scoring contribution was provably always zero; that dead branch went with
  it. `Marketplace.tsx` was renamed to `SkillTemplates.tsx` to stop reading as a
  duplicate of the domain-pack marketplace.

### Added
- **CI coverage floor.** The backend unit lane now runs under coverage with
  `--cov-fail-under=58` (measured 60.64%, minus-2 headroom), so coverage can only
  trend up. `pytest-cov==7.0.0` pinned (the line compatible with pytest 9).
- **CycloneDX SBOMs as a build artifact.** A new `sbom` CI job emits a Software
  Bill of Materials for both dependency trees — backend via `cyclonedx-bom`,
  frontend via Syft (`anchore/sbom-action`, which reads `package-lock.json`
  directly and avoids `npm sbom`'s `npm ls` strictness on optional platform deps).

### Changed
- **The last "KAEOS 10X" branding is gone from the API surface.** The federated,
  polymorphic and predictive routers still carried `KAEOS 10X` OpenAPI tags and
  module docstrings; they now read as what they do.
- **The `/10x` API is now `/advanced`.** The advanced-capabilities router
  (regulatory auto-patch, provenance ledger, federated and polymorphic activity,
  pre-cognition, enterprise-physics simulation) was mounted under `/10x` with a
  tag reading "KAEOS 10X", marketing branding in a governance product's API. It
  is now `/advanced` with a plain "Advanced Capabilities" tag. `/10x` stays
  mounted as a deprecated alias so existing integrations and the e2e suite keep
  working; the route module was renamed `kaeos10x.py` to `advanced.py`.
- **The regulatory auto-patch ledger actor is now named for what it is.** The
  provenance ledger recorded the actor of an auto-generated compliance patch as
  `SYSTEM_L24`, an internal level number, persisted into the audit record. It is
  now `regulatory-autopatch`.
- **The Skill Templates tab id matches its label.** In the Agents view the tab
  labelled "Skill Templates" carried the internal id `marketplace`, a copy-paste
  artifact that read as a duplicate of the domain-pack marketplace. It is now
  `skill-templates`.
- **Every broad exception handler is now observable.** Audited all 308 `except
  Exception` blocks; the 30 that swallowed to a silent default now either narrow
  to the concrete exception, log via `logger.exception/warning`, or carry a
  one-line comment where the swallow is deliberately best-effort. No handler
  swallows an error silently.
- **Eight files over 800 lines were split along natural seams**, every public
  import path preserved: `llm_router.py` → `llm_support`/`llm_simulation`;
  `vendor_adapters.py` → a by-vendor package; `neural.py` → `neural_helpers`;
  `api/client.ts` → `http`/`types`/`endpoints` (barrel); and the
  RealityExperience / PioneerLab / TwinGraph / ConnectorStudio views into
  co-located parts. No source file now exceeds 800 lines.

### Security
- **cryptography `48.0.1` → `50.0.0`** to clear CVE-2026-69247/69248/69249
  (flagged by `pip-audit`); resolves cleanly with `signxml` 5.1.0. Frontend
  `npm audit` is clean at `--audit-level=high` (`brace-expansion` advisory fixed).

### Fixed
- **Hours-saved and cost-saved are no longer fabricated anywhere.** The platform
  documented a `null`-with-note contract for these figures but only honoured it on the
  billing endpoints. `rollup_department_metrics` still derived
  `Department.hours_saved_total` as `tasks_completed * 0.5` hours, and the workforce
  surfaces multiplied a hardcoded loaded rate onto that to produce a cost, stacking two
  fabrications into a confident ROI number with nothing behind it.
  - The producer no longer derives either figure. Nothing in the codebase writes
    `hours_saved_total`, `hours_saved_estimate` or `cost_savings_estimate`.
  - One shared contract, `hours_saved_payload` (`app/workforce/models/core.py`), now backs
    every reader: `/billing`, `/workforce/analytics`, `/workforce/overview`,
    `/workforce/departments` (list and detail). Responses carry `hours_saved_basis`
    (`tenant_supplied` / `no_tenant_baseline`) and a note. A stored `0.0` is read as
    "no baseline configured", never as a measured zero.
  - Cost is only ever derived from hours that are themselves real, and a tenant that
    tracks cost directly keeps that figure even when hours are unset.
  - **Migration `0030`** clears the values the old heuristic had already persisted.
    Without it the new read path would have re-served fabricated numbers under
    `hours_saved_basis: tenant_supplied`, which is worse than the original defect. The
    downgrade is deliberately a no-op: it will not recompute them.
  - The UI renders **"Not measured"** with the reason instead of `0h` / `$0`
    (Workforce Analytics, Department Detail, HR Dashboard), via a new `measured()` helper
    in `src/lib/format.ts`. A measured zero and an unmeasurable one are different claims.
  - `tests/test_hours_saved_honesty.py` locks the contract, including a guard that fails
    the build if any workforce module emits an hours-saved figure without the shared
    helper, and one that fails if the producer ever re-derives the number.
- **One product tagline in the app itself.** The login page, invite page, sidebar, browser
  title and a benchmark prompt each carried a different name ("Epistemic OS",
  "Knowledge-Augmented Enterprise OS", "Enterprise Workforce OS"). All now read
  **The AI Operating System for Companies**.
- **"Not measured" no longer overflows its KPI tile** on Workforce Analytics; the
  unmeasured state renders small and muted so the numeric tiles stay the visual anchors.

### Documentation
- **Every published count re-derived from the tracked source.** A full top-to-bottom
  audit found several figures had drifted as the codebase grew. Corrected: the data
  model is **233 ORM tables across 77 model modules and 29 migrations** (was "47 tables,
  30 migrations"); the API is **316 endpoints across 56 route modules** (was 58);
  **76** service modules (was 88); the frontend is **99 components (45 pages, 18 views,
  34 shared)** (was "49 pages, 31 components"). The `441` E2E-test badge was verified
  correct and now sits alongside the full **900** (441 e2e + 459 unit).
- **Department agent counts corrected in `docs/FEATURES.md`.** Sales is **8** (was 6),
  Support **7** (was 5), Operations **6** (was 5). 41 department agents in total, defined
  as the agent modules under `backend/app/<department>/agents/`.
- **`docs/API.md` now states the API prefix.** Every documented prefix was missing the
  real mount point: routes live under **`/api/v1`**, not at the bare path, so the HR
  employees route is `GET /api/v1/hr/employees`. The WebSocket feed at `/ws/{tenant_id}`
  is the sole exception. README endpoint references corrected to match.
- **`docs/README.md` added.** A documentation index covering product, engineering,
  security/compliance, operations and project docs, and stating the `/api/v1` convention
  once up front.
- **The `hours_saved` honesty claim is now correctly scoped.** The README asserted that
  `hours_saved` and `cost_reduction` "return null". That is true of the metering endpoints
  only; the legacy workforce rollup still derived them from a 0.5h-per-execution heuristic.
  The claim is now scoped to the endpoints where it holds, with the gap documented in
  `docs/KNOWN_LIMITATIONS.md`.
- **Removed an unsourced statistic.** The claim that "most agent pilots never reach
  production" carried no citation and has been dropped rather than attributed after the fact.

### Changed
- **Licensing made unambiguous.** KAEOS source is Apache-2.0 and only that: no dual
  license, no commercial tier, no proprietary grant. `NOTICE` and the README now say so
  explicitly, with a scope table for what the grant does *not* cover (third-party benchmark
  datasets, dependency licenses, the KAEOS name and logo). Clarified that "IP" in
  `app/legal/` (`ip_agent.py`, `models/ip.py`, "IP/patent evaluation") is a Legal-department
  **product feature** for tracking a tenant's own intellectual property, not a license claim
  over KAEOS.
- **One product tagline.** `NOTICE`, `docs/ARCHITECTURE.md` and `frontend/index.html`
  carried three different taglines ("Cognitive Operating System for the Enterprise",
  "Epistemic Operating System", "AI Operating System for Companies"). All now use the
  README's: **The AI Operating System for Companies**.
- **Optional backends labelled as optional.** Neo4j and the LangChain text-splitters are
  imported lazily and are not installed by default; the README no longer implies they are
  part of the running stack.

## [1.9.0] - 2026-08-03 - "Fast Lane"

The performance and quality release: the governed decision pipeline gets
measured, parallelized, and short-circuited - without weakening a single gate -
and four releases' worth of red CI goes green again.

### Performance
- **Per-gate latency instrumentation.** Every gate transition now records its
  wall-time lap. Execution results carry `stage_timings` + `pipeline_ms`, the
  `gate_event` WebSocket payload carries per-gate `ms`, and a rolling in-process
  buffer keeps the last 50 executions' timings.
- **`GET /metrics/latency`.** Where the seconds go, on demand: model-call
  latency by tier and by model (avg/p50/p95/max from metered CostEvent rows)
  plus per-gate wall-time for recent executions.
- **Contested-only debate turn 2.** The debate engine arbitrates after the
  first proposer/advocate exchange; the second exchange now runs ONLY when the
  arbitrator lands in the contested band (0.5 <= confidence < 0.8). A decisive
  debate resolves in 3 sequential reasoning calls instead of 5 - roughly 40%
  off the single largest latency cost in the pipeline - while genuinely
  contested decisions keep the full two-turn scrutiny. Turn-2 context now uses
  the structural compactor instead of unbounded `json.dumps`.
- **Parallel gates.** Gate 1 (compliance) and Gate 2 (fairness) run
  concurrently when both apply - they are independent, and each can make a real
  model call. Compliance-BLOCKER verdict ordering is preserved. Cross-domain
  debate perspectives are likewise gathered concurrently.
- **Frontend stale-while-revalidate.** GETs are cached for 15s in the API
  client: navigating back to a page renders instantly from the last response
  while a background refetch keeps it live. The TTL sits under the 20s
  live-refresh convention (polling pages still hit the network every tick),
  and any mutation flushes the whole cache.

### Fixed
- **CI: backend-e2e-mock lane green again** (red since the v1.5.0 SAML
  commit, through four releases): the stale "SAML returns 501" test now
  asserts the real SP metadata endpoint; the e2e client follows FastAPI's
  trailing-slash 307 redirects; the MCP `list_skills` tool forwards to
  `/skills` (no trailing slash), restoring its `structuredContent` payload.
- **Security: `POST /neural/brain/ingest` now requires the operator role.**
  It shipped in v1.8.0 with no role gate - a default-deny violation caught by
  `test_default_deny` (the other reason the CI lane was red).

### Added
- **Voice ingest.** The brain ingest bar gains a native Web Speech API mic:
  speak a note straight into the company brain (no dependency; the button
  only renders where the browser supports it).
- **Real HR agent personas.** The three HR agent personas were truncated
  placeholder stubs; they are now real working charters (EEOC-safe screening,
  I-9 deadline escalation, HIPAA-bound benefits answers) in the style of the
  engineering pack.
- **Explicit agent skill ownership.** Workforce deployment now links each
  agent's core skill into `DepartmentAgent.skills`, so dossiers and
  agent-to-task edges read explicit ownership instead of relying on the
  skill-id token-match fallback.

## [1.8.0] - 2026-08-01 - "Neural Map"

The company becomes a living map. The Departments surface gains three lenses
(Grid | Neural map | Hierarchy) and the backend gains a composite `/neural`
read layer that turns existing stores into an org-wide graph, derived agent
dossiers, and the first real document-upload ingestion path.

### Added
- **Neural map (free flow).** `GET /api/v1/neural/world` composes the whole
  organization into ONE graph: every department cluster (integrations, agents,
  tasks, capabilities, processes), department brains pinned in horizontal
  sequence, agents floating above their department, shared connectors
  structurally bridging departments, agents linked by their real message log
  (`agent_messages`) and by department peerage, and the company brain at the
  base. Rendered as an Obsidian-style force simulation via the generalized
  `TwinGraph` engine (new `seedPositions` / `territories` / `labelsAlways`
  props; springs adopt the seeded geometry as their rest length).
- **Brain view.** The knowledge core as a dense particle sphere: cluster labels
  inside its ring, every department on the orbit in its brand color, and an
  Obsidian-style "brain in numbers" panel (notes, links, skills, runs, and
  per-domain knowledge bars) that opens when the brain is clicked.
- **Agent and task dossiers.** `GET /neural/agents/{id}/dossier` and
  `/neural/skills/{id}/dossier` derive - live, from real fields, no schema
  change - the autonomy ladder (human led / human assisted / fully autonomous,
  from `always_hitl`, the AutonomyPolicy dial, and execution history), what the
  agent replaces, the human's role, the SOP written out in plain English, the
  skills it breaks into, tool bindings, and its live execution record. Click
  any agent or task node to open the dossier drawer.
- **Dump into the brain.** `POST /neural/brain/ingest` is the platform's first
  real multipart upload endpoint: a note or dropped document becomes a Signal,
  is embedded into the `enterprise_memory` namespace (the copilot's grounding
  store) and appears on the knowledge graph - so what you drop immediately
  changes what the Copilot can cite. Paired with `GET /neural/brain/search`
  (semantic over memory namespaces + keyword fallback over rules and skills)
  and `GET /neural/brain/stats`.
- **Hierarchy.** The chain of command drawn live: Operator, the KAEOS Copilot
  (renamed from "Conductor" - one assistant, one name; the card opens the
  existing copilot), and every department with brand-colored health rings,
  agent rosters, pending-approval count, animated flow lines and live totals.
- **Department Network tab.** Custom-deployed department pages gain a Network
  tab rendering the same living graph scoped to one department, with previous/
  next navigation.

### Changed
- `DepartmentsHub` restructured around the three-lens switcher; the neural
  lens renders full-bleed. `DomainIcon` now exports `domainColor()` so the map,
  hierarchy and knowledge bars share one department palette.

## [1.7.0] - 2026-08-01 - "Pioneer Lab"

Surfaces the advanced engines that were built and proven but had no home, and
fixes a quiet correctness bug that had been degrading every local model call to
deterministic fallback. A "make the real thing reachable" release.

### Added
- **Pioneer Lab.** A consolidated console (`/platform/pioneer-lab`) that finally
  gives a UI to the advanced engines that were built and e2e-tested but had no
  surface: external intelligence (feed a signal, correlate it against the
  Company Brain, raise a proactive alert), org intelligence (change-readiness
  scoring, influence-path planning, live skills topology), what-if simulation
  and macro-shock stress tests, cross-org benchmark with a model-written
  maturity report, and the tamper-evident / regulatory / federated / polymorphic
  engine ledgers plus the data-pipeline catalogs. Every panel calls a real
  endpoint; nothing is decorative.

### Fixed
- **Local LLM calls no longer time out.** The router used a single 30s timeout
  for every provider; a CPU-bound local Ollama model routinely needs minutes to
  generate, so every local reasoning/embedding call timed out and tripped the
  circuit breaker (falling back to deterministic output). Local (`ollama/`,
  `custom/`) models now get their own `LLM_LOCAL_TIMEOUT_SECONDS` (default 240s)
  budget; cloud keeps `LLM_TIMEOUT_SECONDS` (default 30s).
- **Human-readable copy across admin/detail surfaces.** 32 sites in 16
  components rendered raw machine tokens (`SUCCESS_CLEAN`, snake_case confidence
  tiers, entity/conflict/question types, skill IDs, wargame shocks) directly;
  they now route through the shared `humanize()` helper with correct acronym
  handling. Sentence-embedded lowercase tokens were left as-is.

## [1.6.0] - 2026-08-01 - "Living Surface"

A correctness-and-craft release. The honesty, closed-loop and memory work is
independently verified against the code (not just the tests), tenant-scoped
model routing reaches every high-value call site, and the product surface
becomes genuinely live: dashboards refresh themselves, numbers count up, and
meters animate to value.

### Added
- **Tenant-aware LLM routing.** `get_llm_router` / `get_tenant_router` resolve
  the ambient tenant so per-tenant fine-tuned models actually reach chat,
  debate, fairness, compliance, elicitation and the memory / knowledge-base
  embed paths (bare `LLMRouter()` stays the system-job fallback). The tenant
  router is resolved into a local var for the shared Compliance / Fairness
  singletons to avoid a cross-tenant race.
- **Embedding provenance.** `embed()` records the model used and stamps
  `{embedding_model, simulated}` into every vector upsert's metadata, so
  simulated vectors are detectable and re-embedding is possible.
  `ModelEvolutionRun` gains a `prompt_hash` (sha256 of the held-out eval
  prompts) for reproducibility. Migration `0029` (additive).
- **Live, reactive dashboards.** Executive Cockpit, Org Pulse, Mission Control,
  the seven domain dashboards, Departments and Infrastructure now refresh on a
  20s interval (paused when the tab is hidden). Hero KPIs animate with a new
  `CountUp` (rAF ease-out, honors `prefers-reduced-motion`); progress rings and
  meters transition to value instead of snapping.
- **Shared `humanize()` helper** turns raw enum / code tokens into plain-English
  Title Case, applied across the app shell, dashboards and views so no raw
  status/type/route codes leak to users.

### Changed
- **Type floor raised to 11px** across the app (no sub-11px text anywhere).
- Emoji / dingbats replaced with lucide icons; em-dashes removed from all
  user-facing copy; a global `prefers-reduced-motion` block plus rAF guards on
  the animated graph views.
- Inter font de-duplicated; seven unused frontend dependencies removed
  (recharts, framer-motion, radix, class-variance-authority, tailwind-merge,
  clsx).

### Fixed
- **Mission budget accounting.** A mission's gates spend real model budget even
  when a step pauses for HITL, escalates or fails, but `spent_usd` was only
  incremented on clean successes; a mission that repeatedly paused or failed
  could keep spending without ever tripping its budget block. Cost now accrues
  on every step result.

### Verified (no change required)
- Independent code-level review confirmed the hallucination-handling, closed
  loop (Gate 5b fail-closed, L1 outcome vocabulary, L4 attribution, federated
  peer-evidence) and enterprise-memory wiring from the prior release are
  production-sound.

## [1.5.0] - 2026-07-31 - "Federated Front Door"

A production-readiness release: enterprise SSO reaches parity (real SAML 2.0
alongside OIDC), the last orphaned backends get self-service UIs, every data
page fails loudly instead of silently, and KAEOS ships a real Kubernetes story.

### Added - Enterprise SAML 2.0 SSO
- **Real, signature-verified SAML 2.0** replaces the `/auth/sso/saml` 501 stub.
  KAEOS is now a SAML Service Provider (SP-initiated HTTP-Redirect/POST):
  - `GET /auth/sso/saml/metadata` publishes SP metadata for the IdP admin.
  - `GET /auth/sso/saml/login` issues a signed-`RelayState` AuthnRequest and
    redirects to the tenant's IdP.
  - `POST /auth/sso/saml/acs` verifies the assertion's XML-DSig signature
    (`signxml`, pure Python - no `xmlsec` C library, so it installs on every
    platform) against the configured IdP certificate, reads **only the verified
    subtree** (defeating XML Signature Wrapping), and enforces Status, validity
    windows with clock skew, `AudienceRestriction` == this SP, `Recipient` ==
    this ACS, `InResponseTo` == the request we issued, and single-use assertion
    IDs (Redis-backed, in-process fallback). Encrypted assertions are refused
    rather than accepted unverified.
- Both protocols share one provisioning path (`sso.provision_and_login`), so JIT
  user creation and role mapping are identical. Login-page "Continue with SSO"
  and the Settings -> Security admin surface now handle OIDC **and** SAML.
- Connection registry gains `idp_sso_url` + `idp_x509_cert` (migration `0027`;
  the cert is public, so plaintext, unlike the Fernet-encrypted OIDC secret).
- Tests: `tests/test_saml.py` - a locally-generated cert signs a real assertion
  and every attack (tamper, wrong cert, wrong audience/recipient, expiry, wrong
  `InResponseTo`, unsigned, replay) is refused.

### Added - Self-service platform access (de-orphaned billing + enterprise)
- New Settings -> Platform surface (`PlatformAccessSettings`): **Metered Usage
  & ROI** (billing.py), **Outbound Webhooks** (create/list/delete with an event
  picker), and **Platform API Keys** (issue-once with a copy-guard, list,
  revoke). All admin-gated.
- Backend: tenant-scoped self-service API-key routes (`GET/POST/DELETE
  /api-keys`) with security-event audit; `core.auth` gains `list_api_keys` and a
  tenant-scoped revoke so an admin can only touch their OWN keys (a prefix guess
  cannot reach another tenant). Fixed the stale `/enterprise/*` client paths
  that 404'd against the bare `/api/v1` mount.

### Added - Kubernetes / Helm
- `deploy/helm/kaeos`: backend + frontend Deployments, Services, opt-in Ingress
  (`/api` + `/ws` + `/health` to backend, `/` to the SPA), backend HPA (2->8 on
  70% CPU), and a Secret. Migrations run as a pre-install/pre-upgrade **Helm-hook
  Job** as the owner role, so replicas never race on DDL and app pods stay
  non-owner (RLS applies). Managed Postgres+pgvector / Redis are values-driven.

### Fixed - Fetch errors surface with retry
- Ten data pages either swallowed a failed fetch to an empty default or had a
  `.then` with no `.catch` that hung the loading spinner forever. Each now
  renders `<BrainError onRetry>` when its anchor call fails, keeping partial data
  where a page legitimately aggregates several calls (SkillsRegistry,
  RulesExplorer, InfrastructureDashboard, WorkforceDashboard, WorkforceAnalytics,
  DepartmentsHub, Automation, ExtractionHub, DomainPackMarketplace, MyWork).

## [1.4.1] - 2026-07-28 - "Green Lane"

Patch release. CI/tooling only; no application code or API changes.

### Fixed - CI (frontend-build lane)
- **Vitest workers crashed on startup under Node 20.** `jsdom` pulls in
  `undici@7.29.0`, whose `CacheStorage` constructor calls
  `worker_threads.markAsUncloneable` - an API that only exists on Node
  `>=20.19.0` / `>=22.12.0`. The workflow pinned `node-version: "20"`, which the
  runner resolved to a 20.x build below that floor, so every test worker died
  with `webidl.util.markAsUncloneable is not a function` (7 errors / no tests)
  before a single test ran. Bumped both `setup-node` steps (`frontend-build`
  and `security-scan`) to Node 22 (LTS) and added `engines.node ">=20.19.0"` to
  `frontend/package.json` to document the floor. Suite is green: 7 files /
  43 tests.

## [1.4.0] - 2026-07-28 - "Provable Trust"

Closed the remaining known-limitations with real, tested code and made the
governance/privacy surface visible: a prompt-injection detection-and-neutralization
layer, erasure that reaches stored blobs and survives backup restores, real semantic
search on the zero-key dev path, and an audit-readiness controls report (mapped to
SOC 2 / ISO 27001 / GDPR / SOX with code+test evidence) surfaced in the Compliance UI
alongside a Data Subject Erasure panel. Also a ~2.4x faster unit test lane. Migrations
advance to `0026`.

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
