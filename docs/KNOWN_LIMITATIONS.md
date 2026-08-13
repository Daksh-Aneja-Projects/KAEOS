# Known Limitations & Roadmap

Back to the [README](../README.md). Related: [Security model](SECURITY_MODEL.md) |
[Deployment](DEPLOYMENT.md)

We'd rather you read this from us than find it. What's shipped and verified vs. what's ahead:

**Verified today:** the governance spine (gates fail closed), per-tenant PostgreSQL row-level
security (isolation proven on Postgres - cross-tenant reads scoped, cross-tenant writes blocked),
default-deny authorization on every mutating endpoint (199/212 explicitly gated, the rest a reviewed
allowlist, both regression-locked), BYOK LLM routing with real cost metering, a 441-test E2E suite
green on SQLite **and** Postgres+pgvector, and real-data benchmarks that report losses as well as wins.

Here is exactly what is shipped versus in progress. We treat this candor as an asset, not an apology.
Each item below states the capability, its honest boundary, and anything still ahead.

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
  mutation appears. In the current code **199 of 212** write endpoints carry an explicit gate. The
  remaining **13** are the reviewed allowlist: 4 intentionally public auth routes (`login`/`logout`/
  `accept-invite`/SSO), 2 HMAC-authenticated external ingest endpoints (Workday/Salesforce/SIEM relays
  that cannot hold a KAEOS JWT, signed over the raw body), 3 MFA self-service endpoints (a user manages
  their own second factor), 2 viewer-level self-actions (marking one's own items read), and 2 read-like
  routes that produce no state change (skill `explain`, chat `stream`). None of the 13 mutate persistent
  business state. Coverage is regression-locked by both `tests/test_default_deny.py` (the default-deny
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
  against*, not an external attestation.
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
- **Write-back to external systems of record is Salesforce + generic REST today.** All 22
  connectors ingest (read/sync) for real. Pushing governed changes back INTO the external system
  is implemented for Salesforce (Account/Opportunity) and a generic REST sink; Workday write-back
  is an explicit not-implemented stub and the remaining adapters return `"no write-back adapter"`
  rather than pretending. Governed writes to targets without an adapter land in KAEOS's internal
  governed object store - still idempotent, reversible, drift-monitored, and provenance-chained,
  but internal until that target's adapter ships. **Boundary:** a claim of "we updated your ERP"
  is only true for the systems above; everywhere else KAEOS records what it *would* write and
  keeps it reversible. Bidirectional adapters for the top systems of record are the active
  integration roadmap.
- **Industry verticals are not yet load-bearing.** The seven "departments" are functional
  domains (HR, Finance, Support...), not industry verticals. The `industry_vertical` captured at
  onboarding is stored and displayed but does not yet change which packs, compliance frameworks,
  seeds, or gate policies a tenant gets - a bank and a pharma company currently receive the same
  functional shell with their industry as a label. There are **no built-in deterministic engines
  for 21 CFR Part 11 / GxP, KYC / AML, SR 11-7 model risk, or ECOA adverse-action** today;
  compliance tags name the frameworks a skill is *built against* (see the certification item
  above), and the gates enforce process (approval, audit, provenance), not statutory rules.
  **Roadmap:** make `industry_vertical` select packs, frameworks and gate policy, and ship one
  real industry pack end-to-end with a deterministic statutory checker.
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
