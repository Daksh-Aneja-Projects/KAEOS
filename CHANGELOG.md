# Changelog

All notable changes to KAEOS are documented here. This project adheres to
[Semantic Versioning](https://semver.org/).

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
- Standard JWT (jose) sessions; BYOK connector credentials encrypted at rest
  (PBKDF2-derived key); hardened agent code sandbox; fail-fast production config
  validation (refuses to boot on insecure config or SQLite-in-production).

### Verified
- Full end-to-end suite (419 tests / 426 items) green on SQLite **and** on
  PostgreSQL + pgvector against a live server with a local LLM.
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
