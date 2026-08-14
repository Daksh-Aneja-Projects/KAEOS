# KAEOS Documentation

Back to the [project README](../README.md).

All API paths in these documents are relative to the API prefix **`/api/v1`**
(configurable via `API_PREFIX`). There are two exceptions, both mounted bare at
the root: the WebSocket feed at `/ws/{tenant_id}`, and the public `/status`
endpoint (no auth; db/redis/llm reachability, version and uptime, deliberately
no business metrics). Against a default local stack the base URL
is `http://localhost:8001/api/v1`, and the live Swagger UI is at
`http://localhost:8001/docs`.

## Start here

| If you want to... | Read |
|-------------------|------|
| Run KAEOS locally for the first time | [SETUP.md](SETUP.md) |
| Understand what the product does | [FEATURES.md](FEATURES.md) |
| Understand how it is built | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Call the API | [API.md](API.md) |
| Know what is *not* done | [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md) |

## Reference

### Product

| Document | Covers |
|----------|--------|
| [FEATURES.md](FEATURES.md) | The 10 departments and their agents, gates, missions, Foundry, Neural Map, screenshots |
| [BENCHMARKS.md](BENCHMARKS.md) | Real-data benchmark methodology and results, wins and losses, and why the regulated verticals are validated differently |
| [CONNECTORS.md](CONNECTORS.md) | The 22 live connector adapters, authority weighting, PII handling, write-back |

### Engineering

| Document | Covers |
|----------|--------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System design, project structure, request path, performance |
| [API.md](API.md) | Department and platform endpoint reference, including the healthcare, lending, procurement, ops-console, branding and metrics surfaces |
| [BYOK.md](BYOK.md) | Bring your own model: tiers, probe battery, ceiling derivation, data residency |
| [TESTING.md](TESTING.md) | Test suites (backend unit, e2e, frontend), CI lanes, how to run each locally |

### Security and compliance

| Document | Covers |
|----------|--------|
| [SECURITY_MODEL.md](SECURITY_MODEL.md) | Multi-tenancy, row-level security, authn/authz, SSO and SCIM, CSP, prompt-injection screening |
| [COMPLIANCE_POSTURE.md](COMPLIANCE_POSTURE.md) | Control coverage, the deterministic statutory checkers behind the regulated departments, and the audit-readiness evidence endpoint |
| [../SECURITY.md](../SECURITY.md) | How to report a vulnerability |

### Operations

| Document | Covers |
|----------|--------|
| [DEPLOYMENT.md](DEPLOYMENT.md) | Deploying KAEOS, the Alembic chain (currently head `0044`), and the Helm chart under `deploy/helm/kaeos` |
| [OPS_RUNBOOK.md](OPS_RUNBOOK.md) | Day-2 operations, monitoring, incident procedures |
| [RUNBOOK.md](RUNBOOK.md) | Model and LLM operations, including local Ollama troubleshooting |

### Project

| Document | Covers |
|----------|--------|
| [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md) | Every known gap, kept current |
| [../CHANGELOG.md](../CHANGELOG.md) | Release history |
| [../CONTRIBUTING.md](../CONTRIBUTING.md) | Development workflow, commit conventions, inbound = outbound licensing |
| [../CODE_OF_CONDUCT.md](../CODE_OF_CONDUCT.md) | Contributor Covenant |
| [../LICENSE](../LICENSE) / [../NOTICE](../NOTICE) | Apache 2.0 and required attributions |

## Conventions used in these docs

- **Numbers are counted, not estimated.** Figures quoted in the README and here
  are derived from the tracked source at the current commit. If you change the
  code, re-count before changing the number.
- **Absent beats invented.** Where a metric cannot be measured honestly, the
  platform returns `null` with a note rather than a plausible-looking figure.
  See "What we refuse to fake" in the [README](../README.md).
- **Roadmap items are labelled.** Anything not shipped lives in
  [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md), not in the feature docs.
