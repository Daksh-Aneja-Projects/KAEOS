# Known Limitations & Roadmap

Back to the [README](../README.md). Related: [Security model](SECURITY_MODEL.md) |
[Deployment](DEPLOYMENT.md)

We'd rather you read this from us than find it. What's shipped and verified vs. what's ahead:

**Verified today:** the governance spine (gates fail closed), per-tenant PostgreSQL row-level
security (isolation proven on Postgres - cross-tenant reads scoped, cross-tenant writes blocked),
BYOK LLM routing with real cost metering, a 441-test E2E suite green on SQLite **and**
Postgres+pgvector, and real-data benchmarks that report losses as well as wins.

Here is exactly what is shipped versus in progress. We treat this candor as an asset, not an apology.

**Not done yet / roadmap:**

- **RBAC coverage.** The `viewer`/`operator`/`admin` roles are defined and enforced today on
  consequential and mutating endpoints: creation, update, deletion, skill execution, HITL approval,
  connector credentials, deployments, pack install/uninstall, elicitation answers, external-signal
  ingest, schema-mapping confirmation, ETL pipeline runs, training-feedback capture, circuit-breaker
  resets, autonomous tool synthesis (admin-only), and model-evolution promotion (admin-only). In the
  current code **106 of 132** write
  endpoints carry an explicit role or admin-secret gate. The remaining 26 are 3 intentionally public
  auth routes (`login`/`logout`/SSO) plus 23 tenant-scoped **read/compute/simulation/telemetry-ingest**
  endpoints (analysis, what-if, physics/shock simulation, agent-to-agent protocol messages, cost
  telemetry ingest) - these run no persistent business-state mutation and are protected by tenant
  isolation. Coverage is regression-locked by `tests/test_rbac_coverage.py`, which introspects the live
  route table and fails if any gate is dropped.
- **Security audit logging.** The access/security audit log (`SecurityAuditLog`: auth successes and
  failures with lockout, RBAC denials, HITL decisions, config changes, connector and export actions)
  is wired to real runtime events across the auth service and ~20 route modules in this release. It is
  a best-effort writer (a logging failure never blocks the request) and is distinct from the
  hash-chained AI-decision provenance ledger, which is a separate system and was always real; do not
  conflate the two.
- **Prompt-injection defense.** Mitigations are in place (source-authority weighting so untrusted
  content ranks below systems of record, tool allow-lists, gated execution), but this is defense in
  depth, not a complete solution. Treat connected content as untrusted input.
- **Data-protection features.** Right-to-erasure and configurable retention windows are now
  exposed through the API and enforced, alongside the data-residency (local-LLM-only) mode.
  Subject erasure (`POST /privacy/erasure`, admin-gated, audit-logged) tombstones direct
  identifiers on the HR PII tables; retention windows (`GET/PUT /privacy/retention`,
  `POST /privacy/retention/apply`) hard-delete rows past a configurable age for a curated
  allow-list of **transient telemetry** classes only - the allow-list structurally cannot target
  the hash-chained provenance ledger or the Foundry training lineage, and every class is **opt-in**
  (nothing is purged until an admin enables it). Honest boundaries remain: erasure does not reach
  object-storage blobs, vector embeddings, or backups (delete those via their own layers), and the
  scheduled cross-tenant sweep needs the background-job leader lock before it is safe on multiple
  replicas. Validate all of this against your own obligations before relying on it.
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
  personal data in production. Compliance tags in-product describe the frameworks a pack is *built
  against*, not an external attestation.
- **AI Foundry fine-tuning.** Phase 2 (dataset curation) is live, and Phase 3's
  **evaluation-and-gated-promotion** loop is now live: a candidate model is measured against the
  tenant's baseline on held-out governed examples and, if it genuinely wins, promoted through a human
  gate. What is **still not implemented** is the weight-training step itself - KAEOS does not fine-tune
  models; the actual training is external/pluggable, and a simulated evaluation can never promote.
  Phases 4-5 (specialized models, autonomous foundry) remain roadmap.
- **Simulation surfaces.** The enterprise "what-if"/physics and evolution-fitness surfaces are
  parameterized simulations over configurable archetypes, labelled as such, not models learned
  from your data.
- **Rate limiting** is per-process (in-memory); front it with a shared limiter for multi-instance deploys.
- **Semantic search** uses pgvector on Postgres; the zero-dependency SQLite dev path uses keyword
  (TF-IDF) matching, not embeddings.

**Before a production client:** load testing, an independent security/penetration test, and - if
upgrading an existing install - a one-time connector-credential re-encryption. See
[DEPLOYMENT.md](DEPLOYMENT.md).
