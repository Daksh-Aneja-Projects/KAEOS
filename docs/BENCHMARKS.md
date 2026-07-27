# Real-Data Benchmark (validation on real enterprise datasets)

Back to the [README](../README.md). Related: [Testing](TESTING.md)

KAEOS's decision logic is scored against **real, human-authored enterprise data** - not
synthetic seed. Seven public datasets (IBM HR attrition, a real ServiceNow incident log,
customer support tickets, sales lead conversion, procurement POs, IBM accounts-receivable
late-payment histories, and CUAD v1's 510 expert-annotated SEC contracts) are mapped to
KAEOS domains - one per department - and its classifiers are measured against the recorded
human outcomes.

```bash
cd backend && python -m benchmark.real_data.run --limit 5000   # writes benchmark/REAL_DATA_BENCHMARK.md
```

## Headline results (deterministic path - the rule-based safety net, no LLM)

| Domain | Real dataset | Result |
|--------|-------------|--------|
| **Engineering** | ServiceNow incident log (141k events) | **100% match to the instance's own ITIL priority** - a deterministic impact x urgency identity, i.e. a sanity check that we implement the rule correctly, **not** a predictive-accuracy claim |
| **Finance** | IBM AR late-payment histories (2,466 settled invoices) | **81% accuracy vs 64% baseline** - payment history + dispute status predicts late settlement, with calibrated confidence |
| **HR** | IBM attrition (1,470 employees) | **72% balanced accuracy** on a rare (16%) event - catches flight risk without flooding the queue |
| **Legal** | CUAD v1 (9,358 expert-labelled clause spans, 36 categories) | **39% deterministic-exact** (chance ~3%) - unmistakable clauses classify instantly; the rest route to a human, which is the HITL contract working |
| Sales / Support / Ops | LeadForge / support tickets / procurement | Reported honestly, incl. two datasets whose labels carry **no learnable signal** (documented, not hidden) |

Not every domain beats its baseline: on these datasets some domains (notably HR, Sales, and
Support) land at or below the naive baseline rather than above it, and those results are reported
transparently - not spun as wins - in the underlying `benchmark/REAL_DATA_BENCHMARK.md` report.

The benchmark is repeatable and committed; raw datasets are gitignored (licensed) with their Kaggle
refs recorded for reproduction. This **replaces** the previous `benchmark_reports/*.json`, which held
fabricated numbers with no dataset behind them.

## Onboard a real company

`python -m scripts.onboard_real_company` loads all seven datasets into a
single second tenant (`tenant_realco`, "RealCo, Inc.") - real employees, tickets, incidents, leads,
POs, AR invoices with actual settle dates (so aging/DSO figures are computed from history, not
invented), and SEC-filed contracts with expert-labelled, risk-graded clauses. Every record also
becomes a Signal into the Company Brain. View with header `X-Tenant-ID: tenant_realco`. This is the
client-onboarding scenario end to end, and it has caught real bugs the synthetic seed never could -
a severity-downgrade bug, and a cross-tenant leak in the signals feed.

## Agent grounding validation

Every domain agent loads the real entity (ticket text, contract
terms, budget numbers, case facts) into its LLM context before reasoning - an audit found 22 agents
passing only opaque IDs, which left the model classifying an identifier instead of content. All are
now grounded, and `python scripts/validate_domain_agents.py` runs each one through its full gated
pipeline against real rows, verifying both the outcome and that the entity's actual content reached
the model (report: `benchmark/agent_validation_report.json`).
