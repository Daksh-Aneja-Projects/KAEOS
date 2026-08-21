# Known Limitations & Roadmap

Back to the [README](../README.md). Related: [Security model](SECURITY_MODEL.md) |
[Deployment](DEPLOYMENT.md)

We'd rather you read this from us than find it. What's shipped and verified vs. what's ahead:

**Verified today:** the governance spine (gates fail closed), deterministic statutory checkers
backing the regulated departments (an unbacked compliance tag returns `UNBACKED`, which blocks -
never a silent pass), per-tenant PostgreSQL row-level security (isolation proven on Postgres -
cross-tenant reads scoped, cross-tenant writes blocked), default-deny authorization on every
mutating endpoint (293 of 308 mutating paths explicitly gated, the remaining 15 a reviewed
allowlist where another authenticator applies - an HMAC body signature, the Stripe signature, a
signed SAML assertion, `verify_admin_secret`, or the caller's own session - all regression-locked),
BYOK LLM routing with real cost metering, a 1,392-test unit lane plus a 443-test E2E suite green on
SQLite **and** Postgres+pgvector (the E2E lane last run end to end against a real local model:
440 passed, 3 skipped, 0 failed), and real-data benchmarks that report losses as well as wins.

Here is exactly what is shipped versus in progress. We treat this candor as an asset, not an apology.
Each item below states the capability, its honest boundary, and anything still ahead.

**Not done, and blocking a public launch.** These are operational and legal, not code; the
codebase itself carries no open critical or high finding from the standing pre-launch audit.

- **The database restore drill has not been run.** Automated backups exist; a backup nobody has
  restored is a hypothesis, not a recovery plan. RPO/RTO stay unproven until a restore is timed.
- **SPF, DKIM and DMARC are not configured** for the sending domain, so transactional mail
  (invites, password resets, mission checkpoint alerts) will be treated as unauthenticated by
  receiving servers.
- **KAEOS has no Privacy Policy or Terms of Service of its own.** There is no public legal
  surface in the app today; `/departments/legal/privacy` is the *product's* GDPR department -
  the tooling a tenant uses to run their own privacy operations - not our terms. Deliberately
  not scaffolded with placeholder text: a privacy page that misstates how data is handled is
  worse than no page.

**Capabilities, honest boundaries, and roadmap:**

- **`hours_saved` requires a tenant baseline, and is null until it has one.** Hours-saved
  needs two inputs KAEOS cannot observe: how long a task took a person before automation,
  and that person's loaded hourly cost. It was once derived as
  `tasks_completed * 0.5` hours by `rollup_department_metrics`, with a hardcoded rate
  multiplied onto it downstream to yield a cost, so both numbers looked measured and had
  nothing behind them. **Resolved:** the producer no longer derives either figure; every
  reader (billing, workforce analytics, department list and detail, workforce overview)
  routes through one shared contract (`hours_saved_payload` in
  `app/workforce/models/core.py`) that reports `null` plus a note and a `hours_saved_basis`
  of `no_tenant_baseline`; migration `0030` clears the values the heuristic had already
  written, so stale fabricated figures are not re-served as `tenant_supplied`; and the UI
  renders "Not measured" instead of `0h`, since a measured zero and an unmeasurable one are
  different claims. `tests/test_hours_saved_honesty.py` locks all of it, including a guard
  that fails the build if any workforce module emits an hours-saved figure without the
  shared contract. **Boundary:** these figures stay null until a tenant configures a
  per-skill human baseline and rate. KAEOS provides the plumbing, not the numbers.
- **RBAC coverage.** The `viewer`/`operator`/`admin` roles are defined and enforced under a
  **default-deny** policy: every state-changing endpoint must carry an authorization gate
  (`require_role`, `require_service_or_role`, or the out-of-band `verify_admin_secret`) or be on a
  short, reviewed allowlist, and `tests/test_default_deny.py` fails the build the moment a new ungated
  mutation appears. In the current code **227 of 242** write endpoints carry an explicit gate. The
  remaining **15** are the reviewed allowlist: 4 intentionally public auth routes (`login`/`logout`/
  `accept-invite`/SAML ACS), 2 HMAC-authenticated external ingest endpoints (Workday/Salesforce/SIEM
  relays that cannot hold a KAEOS JWT, signed over the raw body), 1 Stripe billing webhook (verified
  by Stripe signature, which is the same pattern), 3 MFA self-service endpoints (a user manages their
  own second factor), 2 viewer-level self-actions (marking one's own items read), and 3 read-like
  routes that produce no state change (skill `explain`, `compliance/check`, chat `stream`). None of
  the 15 mutate persistent business state. Coverage is regression-locked by both
  `tests/test_default_deny.py` (the default-deny
  lint) and `tests/test_rbac_coverage.py` (which introspects the live route table and fails if any gate
  is dropped).
- **Security audit logging.** The access/security audit log (`SecurityAuditLog`: auth successes and
  failures with lockout, RBAC denials, HITL decisions, config changes, connector and export actions)
  is wired to real runtime events across the auth service and ~30 route and service modules in this
  release. It is a best-effort writer (a logging failure never blocks the request) and is distinct from
  the hash-chained AI-decision provenance ledger, which is a separate system and was always real; do not
  conflate the two.
- **Prompt-injection defense.** Untrusted/connected content is now screened by a dedicated
  detection-and-neutralization layer (`app/services/prompt_guard.py`): a curated pattern battery
  scores instruction-override, role-manipulation, prompt/secret exfiltration, guardrail-bypass,
  tool/command smuggling, data-exfiltration, fake-role-turn and encoded-payload attacks; matched
  command spans are redacted; and untrusted text is fenced as data before it enters an LLM context.
  It is wired into the ingestion pipeline (high-risk signals are quarantined) and composes with
  source-authority weighting, tool allow-lists and the HITL gates. This is still defense in depth,
  not a complete solution - an adaptive attacker can evade any single heuristic, which is exactly why
  the downstream gates exist. Treat connected content as untrusted input.
- **Data-protection features.** Right-to-erasure and configurable retention windows are now
  exposed through the API and enforced, alongside the data-residency (local-LLM-only) mode.
  Subject erasure (`POST /privacy/erasure`, admin-gated, audit-logged) tombstones direct
  identifiers on the HR PII tables **and purges the subject's vector embeddings from the semantic
  store** (best-effort: a vector-store outage never aborts the DB erasure that already committed).
  Retention windows (`GET/PUT /privacy/retention`, `POST /privacy/retention/apply`) hard-delete rows
  past a configurable age for a curated allow-list of **transient telemetry** classes only - the
  allow-list structurally cannot target the hash-chained provenance ledger or the Foundry training
  lineage, and every class is **opt-in** (nothing is purged until an admin enables it). The scheduled
  cross-tenant retention sweep is now **leader-guarded** (see the background-job leader lock below), so
  it is safe on multiple replicas - only the elected leader runs it. Erasure now reaches the blob
  layer too: `erase_subject`/`purge_tenant` delete the actual stored files (resume/document blobs) via
  `app/core/polystore/blob_store.py` (local filesystem, plus best-effort S3/GCS when those SDKs are
  configured), not just the DB pointer. Backups are handled with the standard deletion-journal pattern:
  every erasure is journaled (employee id + a SHA-256 of the email, never raw PII) and
  `POST /privacy/erasure/replay` re-applies them after a backup restore, so a restore cannot silently
  resurrect a deleted subject. Honest boundaries remain: replay re-erases after a restore rather than
  reaching into backup files in place, external log sinks are out of scope, and free-text prose
  elsewhere that may mention a subject's name is out of scope. Validate against your obligations.
- **Background jobs are leader-elected.** The singleton loops (PreCog ambient loop, event-bus worker,
  decay scheduler, retention sweep) now elect a single leader automatically, so every replica boots
  identically and only one runs them. The lock picks the best available backend - **Redis**
  (`SET NX PX` + atomic CAS renew/release), falling back to a **Postgres advisory lock**, and finally
  to **local always-leader** for single-instance/SQLite dev. A crashed leader's lease expires and a
  follower takes over within one TTL. `RUN_BACKGROUND_JOBS=false` still pins a replica to pure API
  duty. Verified by `tests/test_leader_lock.py`. (The long-running loops fail over on the next TTL;
  the periodic scheduler jobs additionally self-guard on `is_leader` every tick.)
- **Not certified for regulated employee data.** KAEOS has not been independently certified (SOC 2,
  ISO 27001, HIPAA, etc.) and is not yet cleared for processing regulated employee or other sensitive
  personal data in production. Certification is a third-party AUDIT that software cannot self-grant.
  What KAEOS ships is **audit-readiness**: `GET /compliance/controls` returns a controls-evidence
  report (`app/services/compliance_controls.py`) that inventories the implemented technical controls -
  RLS, default-deny RBAC, encryption at rest, audit logging, hash-chained provenance, erasure,
  retention, PII scrub, prompt-injection screening, HITL gates, leader election, backup+replay - and
  maps each to the relevant SOC 2 / ISO 27001 / GDPR / SOX criteria with code and test evidence. The
  report explicitly lists the external items (the attestation itself, an independent penetration test)
  and never marks them satisfied. Compliance tags in-product describe the frameworks a pack is *built
  against*, not an external attestation. This applies to the regulated verticals too, and the
  distinction matters most there: shipping deterministic HIPAA and 42 CFR Part 2 checkers means the
  gates enforce those rules on the facts they are given. It does **not** make KAEOS a certified
  business associate, and no software can sign your BAA for you.
- **AI Foundry fine-tuning.** Phase 2 (dataset curation) is live; Phase 3's
  **evaluation-and-gated-promotion** loop is live (a candidate model is measured against the tenant's
  baseline on held-out governed examples and, if it genuinely wins, promoted through a human gate); and
  the **L2 external fine-tune bridge** is now live too - `POST /foundry/finetune/submit` exports the
  tenant's curated positive examples to a pluggable provider (real `OpenAIFineTuneProvider`, or an
  honest `NullFineTuneProvider` that fails loudly rather than fabricate a model), a leader-guarded
  scheduler polls each job to completion, and on success it **auto-triggers a real evaluation**;
  promotion stays human-gated. What KAEOS deliberately does **not** do is run the weight-training step
  itself - that computation is external/pluggable by design (KAEOS orchestrates and governs it), and a
  simulated evaluation can never promote. Phases 4-5 (specialized models, autonomous foundry) remain
  roadmap.
- **Maker-checker applies to rules created from now on.** New rules (operator-typed,
  bulk-imported, or AI-synthesized from regulatory text) land non-executable and require a
  different authenticated identity to validate them into execution. Rules that existed before
  this control keep their current executability - re-review them at your own pace; the
  provenance ledger records who validated what from here forward.
- **Provenance ledger: entries written before the 2026-08 unification are unverifiable.** The
  ledger previously had five writers using incompatible hash schemes (one stored a random UUID in
  the integrity column), which made end-to-end verification impossible and produced false
  "TAMPERED" verdicts. All writers now go through one signed scheme (HMAC-SHA256, key derived
  from `SECRET_KEY`) with explicit parent pointers, per-tenant chains, database-serialized
  appends, and an end-to-end verifier; on Postgres the app role's UPDATE/DELETE on the table is
  revoked. **Boundary:** rows written before the unification carry no schema version and are
  reported as `legacy` (unverifiable) - absence of proof is not proof of tampering, and the
  verifier says so instead of guessing. Rotating `SECRET_KEY` invalidates HMAC verification of
  rows signed under the old key; export the ledger before rotating if evidence continuity
  matters.
- **Write-back to external systems of record covers six adapters today.** All 22
  connectors ingest (read/sync) for real. Pushing governed changes back INTO the external system
  is implemented for **ServiceNow** (incident/task/problem/change via the Table API),
  **Salesforce** (Account/Opportunity), **Zendesk**, **Jira**, **Slack**, and a **generic REST**
  sink; each create is idempotent, stamping the idempotency token on a native field
  (ServiceNow `correlation_id`, a `[kaeos:...]` marker on Salesforce) and probing for it first, so
  a create whose HTTP response was lost is not duplicated on retry. Workday write-back
  is an explicit not-implemented stub (it needs a customer tenant and ISU credentials; no public
  sandbox exists) and the remaining adapters return `"no write-back adapter"`
  rather than pretending. Governed writes to targets without an adapter land in KAEOS's internal
  governed object store - still idempotent, reversible, drift-monitored, and provenance-chained,
  but internal until that target's adapter ships. The outbound queue isolates failures per write
  and dead-letters after a maximum attempt count, so one unreachable endpoint no longer blocks
  every other tenant's queue (`tests/test_writeback_reliability.py`). **Boundary:** a claim of
  "we updated your ERP" is only true for the systems above; everywhere else KAEOS records what it
  *would* write and keeps it reversible. Bidirectional adapters for the remaining systems of record
  are the active integration roadmap.
- **Connector INCREMENTAL pull advances a cursor for ServiceNow only.** Every adapter pulls its
  most-recently-updated window each pass (bounded by `batch_size`) — an honest fixed-window pull,
  not a false delta promise — but only ServiceNow advances a persisted high-water cursor, so on a
  source with more than `batch_size` changed rows between passes, the overflow is re-fetched next
  pass rather than paged past. **Boundary:** generalizing the cursor is per-adapter work (each
  adapter must surface an `updated_at` watermark AND filter on it); ServiceNow is the reference.
- **Integration-audit follow-ups (2026-08-21): all three closed later the same day.** The
  **re-embed job** now exists (`POST /knowledge/embeddings/reembed-stale` +
  `VectorStore.stale_vectors`): it re-embeds vectors stamped by a previous model on the model the
  router ACTUALLY produces vectors with, refuses honestly on a simulated-only router, and reports
  the required pgvector dimension migration instead of writing garbage when the store rejects the
  new width. **OperatorConsole remediation** is wired: the console shows the scheduler heartbeat
  per background job and the durable job queue with one-click requeue of terminally FAILED jobs.
  The **dead-export sweep** ran via `ts-prune`: after excluding lazy-import default exports and
  in-module uses, the only dead code export was one layout constant (removed). What remains is
  ~100 unused TYPE declarations in `src/types/index.ts` — the unadopted typed API contract
  (pages still call `request<any>`); they carry zero bundle weight and are kept deliberately so
  the typing can be adopted rather than deleted. **Boundary:** adopting those response types
  across the client is its own hardening project.
- **Six per-department connectors are now wired, but unvalidated against the real vendor APIs.**
  The finance accounting (QuickBooks/Xero/NetSuite), engineering issue-tracker, healthcare EHR and
  procurement PO connectors are bridged into the pull catalog (they inherit the scheduler,
  ConnectorCredential and the incremental cursor, and fail gracefully); the credit-bureau connector
  is wired into loan-application intake with an honest "no score, enter manually" fallback; DocuSign
  was already wired, so its duplicate connector was not re-registered. A **mocked contract lane**
  (`tests/test_connector_contracts.py`) now pins the code side of each vendor contract: the exact
  URLs and auth headers sent, the documented response shapes parsed (QuickBooks QueryResponse,
  Xero org-scoped invoices, NetSuite account-scoped records, GitHub issue/PR/run envelopes, FHIR
  Bundles, Coupa purchase orders), and the graceful-failure paths the mesh depends on.
  **Boundary:** the live half still stands — these talk to real external APIs (Intuit, Epic,
  Coupa, Equifax, …) that need real credentials, so each should get one credentialed pass against
  that vendor's sandbox before a tenant trusts the data. The audit's closed loop is now fed end to end: connector pulls bridge into the
  event mesh and embed into the copilot's grounding namespace, BYOK ingests through the real
  scrub+vectorize pipeline, elicitation answers become candidate rules, and the internal event bus
  drives the first cross-department automations (offboarding → IT deprovision, adverse-action →
  compliance review, support escalation → operations signal).
- **The Company Brain proposes; it does not act alone, by design.** The brain reflects on real
  operational signals and proposes missions, but a proposal is inert until a human approves it, and
  approval routes through the governed planner (7 gates per step). This is a deliberate governance
  boundary, not a gap — a self-directing brain that auto-ran missions would be the ungoverned
  autonomy the platform exists to prevent. Two honest v1 boundaries: (1) the observation set is
  five signal sources (autonomy-rate decline, cost spike, SoR drift, mission failures, elicitation
  backlog); more can be added as the metrics store grows. (2) The Mission Control brain panel was
  verified by the type-check build and the backend test suite, not a live authed browser pass —
  the standing constraint that authed views need a real login (a password cannot be entered here)
  applies. The reflection service, governance boundary, dedup/cooldown, meta-learning weight and
  outcome reconciliation are unit-tested end to end.
- **Three regulated verticals are real; `industry_vertical` still is not a switch.** This
  limitation has partly closed. KAEOS now ships **ten** departments: the seven functional
  domains (HR, Finance, Legal, Sales, Support, Operations, Engineering) plus
  **healthcare**, **lending** and **procurement**,
  which are regulated verticals with their own models, agents, API surfaces and migrations. Their
  gates are **deterministic statutory checkers** in `app/compliance/checkers/` - pure functions,
  no LLM, fail-closed, auto-discovered by `@register`: HIPAA minimum-necessary / authorization /
  de-identification and 42 CFR Part 2 for healthcare; ECOA (Reg B adverse action), fair lending
  (four-fifths / disparate impact), TILA and FDCPA for lending; three-way match, segregation of
  duties, spend authorization and OFAC screening for procurement; SOC 2 CC8.1, ISO 27001 and change
  freeze for engineering. A compliance tag with no backing checker returns `UNBACKED`, which is
  **blocking**, and a checker that raises is treated as a BLOCK, so the registry cannot fail open.
  **What remains:** the `industry_vertical` captured at onboarding is still stored and displayed
  but does not itself select packs, frameworks, seeds or gate policy - the vertical departments are
  deployed, not inferred from that field. And there are still **no built-in engines for 21 CFR Part
  11 / GxP, KYC / AML, or SR 11-7 model risk**. Everywhere a department has no statutory checker,
  compliance tags name the frameworks a skill is *built against* (see the certification item above)
  and the gates enforce process (approval, audit, provenance), not statute.
- **Statutory checkers are logic, not a data service.** The checkers decide correctly on the facts
  they are given; they do not fetch those facts. Concretely: OFAC screening matches against a
  **caller-supplied** denied-parties list and does exact normalized matching (a punctuation-only
  difference such as `LLC` vs `L.L.C.` downgrades to ADVISORY rather than blocking) - there is no
  bundled sanctions feed and no fuzzy/alias/phonetic matching, so screening with no list supplied
  returns ADVISORY with a finding, never a pass. The fair-lending four-fifths test needs real
  cohort outcome data and says so when it has none. Wire your own list and data sources.
- **Multi-currency GL rates are tenant-supplied.** Every journal line converts to the tenant base
  currency (`FINANCE_BASE_CURRENCY`, default USD) at post time using the most recent `fin_fx_rates`
  row on or before the entry date, and all GL reporting (trial balance, income statement, balance
  sheet, cash flow) aggregates `amount_in_base` rather than summing native debit/credit columns. A
  reversal re-converts at the **original** entry date, so base amounts offset exactly. **Boundary:**
  KAEOS does not subscribe to a market rate feed. Rates are rows you load. A line whose currency has
  no rate on or before its date is **refused**, not converted at a guess.
- **The stored metric series starts when the rollup starts.** `ts_metric_samples` is written by a
  leader-guarded hourly rollup (`METRICS_ROLLUP_INTERVAL_MINUTES`, default 60) that is idempotent
  per bucket, so dashboards and Time Machine read a recorded series instead of reconstructing it on
  every request. There is **no backfill**: buckets before the rollup first ran are simply absent,
  and a metric with no underlying data in a bucket is not stored at all rather than stored as a
  fabricated `0`. `GET /metrics/timeseries` returns an empty series with a note saying so.
- **Simulation surfaces.** The enterprise "what-if"/physics and evolution-fitness surfaces are
  parameterized simulations over configurable archetypes, labelled as such, not models learned
  from your data.
- **Rate limiting** is a shared per-tenant limiter backed by Redis (a per-minute fixed-window counter
  in Redis, one limit across all workers/replicas) when Redis is reachable; it falls back to a
  per-process in-memory window only for single-instance dev where no Redis is configured. For a
  multi-instance deploy, point every replica at the same Redis so the limit is enforced globally.
- **Semantic search** uses pgvector on Postgres. The SQLite dev path now generates **real embeddings**
  too: when a cloud embedding key is absent, the router routes embeddings to a reachable local Ollama
  model (`nomic-embed-text`) instead of non-semantic pseudo-vectors, so dev semantic search is genuine.
  It falls back to deterministic pseudo-vectors only when no embedding provider (cloud key or local
  Ollama) is available at all.

**Before a production client:** load testing, an independent security/penetration test, and - if
upgrading an existing install - a one-time connector-credential re-encryption. See
[DEPLOYMENT.md](DEPLOYMENT.md).
