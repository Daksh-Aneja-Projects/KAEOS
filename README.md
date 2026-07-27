<div align="center">

# KAEOS

### The AI Operating System for Companies

**A living Company Brain that models the whole organization, then runs real
departments on top of it. Every AI action passes a 7-gate governance pipeline,
so autonomy is not granted, it is earned: the platform probes what your model
can actually do, caps every decision's confidence at that measured ceiling, and
routes anything below the bar (or high-consequence, always) to a human.**

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE) [![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://python.org) [![Tests](https://img.shields.io/badge/E2E_Tests-441-brightgreen.svg)](backend/tests/e2e/) [![Ollama](https://img.shields.io/badge/Local_LLM-Ollama_qwen2.5--coder-purple.svg)](https://ollama.ai)

<br />

![KAEOS - Enterprise Workforce dashboard](docs/screenshots/01-dashboard.png)

<sub>The workforce dashboard: **safe-autonomy rate** (how much ran without a human gate), live departments,
and skills that have *earned* autonomy. Captured from a running instance against PostgreSQL - a live
app on a seeded demo tenant, not a mockup or a design comp.</sub>

**Demo video:** coming soon.

</div>

---

## What it is

Enterprise agent deployments fail for a predictable reason: nobody can say, with
evidence, when an agent should be allowed to act on its own. Teams either gate
everything (and the agents save no one any time) or gate nothing (and one bad
autonomous action ends the pilot). Industry surveys put the fallout plainly:
most agent pilots never reach production.

KAEOS starts with the **org graph**: a live model of departments, capabilities,
agents, processes, employees, vendors, projects, customers, accounts, tickets,
contracts, incidents and purchase orders, built from the tenant's own records.
That is the Company Brain. On top of it run seven pre-built AI departments (HR,
Finance, Legal, Sales, Support, Operations, Engineering & IT Ops) whose agents
read the real work and act on it.

Everything they do passes the same 7-gate pipeline: compliance, fairness,
confidence, human-in-the-loop, adversarial debate, execution, and a hash-chained
provenance ledger. Teams watch live agent work in a shared queue and can approve,
redirect or reject any of it, with per-tenant and per-department permissions and
a full audit trail. Skills accumulate confidence from validated outcomes and lose
it by decay; the platform's headline metric is the **safe autonomy rate**, the
share of work completed without human intervention, computed live from real
executions.

## The differentiator: a measured confidence ceiling

Bring your own model (OpenAI, Anthropic, Mistral, Groq, Cohere, Azure,
self-hosted Ollama, or any OpenAI-compatible endpoint via LiteLLM), and KAEOS
**measures** it. A probe battery - JSON compliance, multi-step reasoning, strict
instruction following - produces a `tier_ceiling`: the maximum confidence any
decision may claim on that model.

Measured example - `phi4-mini` probes at a **0.70 ceiling**: it solves
multi-step arithmetic perfectly (1.0) but fails strict instruction-following
(0.0) and wraps JSON in prose (0.75). Put it on the reasoning tier and an
identical high-confidence skill flips from `SUCCESS_CLEAN` to `PENDING_HITL`.
Swap to a stronger model and autonomy returns.

The ceiling is enforced at **Gate 3 of the agent pipeline itself** - every
domain agent (finance, legal, sales, support, operations, engineering) inherits
it, not just the `/skills` routes. A weak model mechanically routes more of the
whole platform's decisions to humans. If the ceiling lookup itself fails, the
gate fails closed: a conservative failsafe cap routes decisions to a human until
it recovers. Model choice becomes a governance dial, not a gamble. Full detail:
[docs/BYOK.md](docs/BYOK.md).

## What we refuse to fake

The honesty of the numbers is the product, so where a true number is not
measurable, the platform returns nothing rather than something invented:

- **`hours_saved` and `cost_reduction` return `null`, with a note.** They
  require a human-baseline duration and a loaded hourly rate per skill - tenant
  inputs KAEOS cannot measure. They were previously "computed" by multiplying
  executions by a hardcoded 0.5 hours and $50/hour. Invented numbers are worse
  than absent ones, so they are absent.
- **Benchmarks publish losses as well as wins.** On the real-data benchmark,
  some domains (notably HR, Sales, and Support) land at or below the naive
  baseline, and those results are reported transparently - not spun as wins
  ([docs/BENCHMARKS.md](docs/BENCHMARKS.md)).
- **A simulated evaluation can never promote a model.** If a Foundry evaluation
  runs without a live provider, the run is flagged `simulated` and structurally
  cannot win or be promoted - a fabricated score must never drive a model swap.
- **There is no fake trainer.** The Foundry's weight fine-tuning step is
  external/pluggable and the product says so; shipping a fake trainer would
  violate the platform's honesty, so it is absent by design.

## Quick start

```bash
git clone https://github.com/Daksh-Aneja-Projects/KAEOS.git && cd KAEOS
cp .env.example .env    # then set DEV_MODE=true and ENVIRONMENT=development for a local trial
docker compose up --build
```

Frontend at http://localhost:5174, API docs at http://localhost:8001/docs.
Demo data auto-seeds on startup. Full configuration (production mode, secrets,
admin login, local Ollama): [docs/SETUP.md](docs/SETUP.md).

## Documentation

| Topic | Where |
|-------|-------|
| Architecture, project structure, performance | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| Features and product tour (departments, gates, missions, Foundry, screenshots) | [docs/FEATURES.md](docs/FEATURES.md) |
| API reference (department + platform endpoints) | [docs/API.md](docs/API.md) |
| Integrations: 22 live adapters, authority weighting, PII handling | [docs/CONNECTORS.md](docs/CONNECTORS.md) |
| Bring your own model: tiers, probe battery, ceiling derivation, data residency | [docs/BYOK.md](docs/BYOK.md) |
| Real-data benchmarks and methodology | [docs/BENCHMARKS.md](docs/BENCHMARKS.md) |
| Security model, multi-tenancy and RLS, SSO | [docs/SECURITY_MODEL.md](docs/SECURITY_MODEL.md) |
| Testing: E2E suite, CI lanes, how to run | [docs/TESTING.md](docs/TESTING.md) |
| Setup, development, deployment, environment variables | [docs/SETUP.md](docs/SETUP.md) |
| Known limitations and roadmap (the full, unabridged list) | [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md) |
| Deployment runbook | [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) |

## Known limitations

We'd rather you read this from us than find it. KAEOS is not independently
certified (SOC 2, ISO 27001, HIPAA) and is not yet cleared for regulated
employee data. The Foundry does not train model weights (external/pluggable by
design). Prompt-injection mitigations are defense in depth, not a solution.
Rate limiting is per-process; simulation surfaces are parameterized archetypes,
labelled as such, not models learned from your data. The full list, kept
current: [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md).

## Contributing

Please read [CONTRIBUTING.md](CONTRIBUTING.md) before submitting pull requests.
We follow the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md).

## License & attribution

Licensed under the **Apache License 2.0**. See [LICENSE](LICENSE) for the full
text and [NOTICE](NOTICE) for required attributions. Apache 2.0 grants
commercial use, modification, distribution, and patent rights; it requires that
you preserve the copyright/NOTICE attributions and state significant changes.

**Third-party data is NOT covered by this license.** The benchmark datasets
under `backend/data/kaggle_raw/` are gitignored and carry their own licenses
from their respective publishers - see [NOTICE](NOTICE) and each dataset's
Kaggle page before redistributing.

---

<div align="center">

**Cofounders:** Daksh Aneja (Product and Engineering) and Sathya Sankarasubbu
(Sales and Marketing). Built with **Claude** (Anthropic's AI coding tools) as
the AI engineering assistant - across architecture, implementation, security
hardening, and verification. Human-directed and AI-built, and deliberately
honest about what's shipped versus roadmap
([docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md)).

**Built with** FastAPI / SQLAlchemy / LiteLLM / React / TypeScript / Redis / Neo4j / pgvector / Ollama

</div>
