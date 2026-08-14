# API Reference

Back to the [documentation index](README.md) and the [project README](../README.md).
Related: [Architecture](ARCHITECTURE.md) | [Connectors](CONNECTORS.md) |
[Security model](SECURITY_MODEL.md)

All endpoints are documented at `http://localhost:8001/docs` (Swagger UI).

> **Every prefix below is relative to the API prefix `/api/v1`** (set by
> `API_PREFIX`, default `/api/v1`). So the HR employees route is really
> `GET /api/v1/hr/employees`, and against a default local stack that is
> `http://localhost:8001/api/v1/hr/employees`. A handful of routes are mounted
> bare at the app root and are called out explicitly below: the WebSocket feed
> `/ws/{tenant_id}`, the liveness probes `/health` and `/health/live`, the public
> `/status` page, and the ADMIN_SECRET-gated `/admin/security/api-keys`.

The surface is **537 operations under `/api/v1`**, spread across the shared route
modules in `backend/app/api/routes/` and each department pack's own router at
`backend/app/<department>/api/v1/router.py`.

## Department APIs (all require `X-Tenant-ID` or JWT)

**Ten departments.** Reads take the authenticated tenant identity; writes and agent
actions require at least the `operator` role (roles rank `viewer` < `operator` < `admin`).

| Department | Prefix | Key Endpoints |
|-----------|--------|---------------|
| HR | `/hr` | `/employees`, `/requisitions`, `/candidates`, `/time-off-requests`, `/performance-reviews` |
| Finance | `/finance` | `/invoices`, `/vendors`, `/budgets`, `/forecasts`, `/tax/filings`, `/sox-controls` |
| Legal | `/legal` | `/matters`, `/contracts`, `/compliance/obligations`, `/cases`, `/privacy/dsars` |
| Sales | `/sales` | `/leads`, `/accounts`, `/opportunities`, `/forecasts` |
| Support | `/support` | `/tickets`, `/kb/articles`, `/csat/surveys`, `/sla/metrics` |
| Operations | `/operations` | `/projects`, `/resources`, `/vendors`, `/procurements`, `/inspections` |
| Engineering | `/engineering` | `/services`, `/engineers`, `/pull-requests`, `/deployments`, `/incidents`, `/postmortems`, `/dashboard` |
| **Healthcare** | `/healthcare` | `/encounters`, `/disclosures`, `/consent` + `/consent/{id}/revoke`, `/tasks`, `/dashboard`, `/analytics` |
| **Lending** | `/lending` | `/applications` + `/{id}/underwrite` + `/{id}/adverse-action`, `/adverse-action`, `/dashboard` |
| **Procurement** | `/procurement` | `/requisitions`, `/purchase-orders` + `/{id}/approve`, `/goods-receipts`, `/three-way-match/{po_id}`, `/vendors`, `/vendors/screen` |

### Regulated verticals: deterministic statutory gates

Healthcare, Lending and Procurement are regulated verticals, so their gates are not model
judgement. They are **deterministic statutory checkers** in `backend/app/compliance/checkers/`:
pure functions, no LLM, auto-discovered through a `@register` decorator.

| Checker module | Tags |
|----------------|------|
| `healthcare.py` | `HIPAA_MINIMUM_NECESSARY`, `HIPAA_AUTHORIZATION`, `HIPAA_DEIDENTIFICATION`, `PART2` (42 CFR Part 2) |
| `lending.py` | `ECOA` (Reg B adverse action), `FAIR_LENDING` (four-fifths / disparate impact), `TILA`, `FDCPA` |
| `procurement.py` | `THREE_WAY_MATCH`, `SEGREGATION_OF_DUTIES`, `SPEND_AUTHORIZATION`, `OFAC_SANCTIONS` |
| `engineering.py` | `SOC2` (CC8.1 change management), `ISO27001`, `CHANGE_FREEZE` |

They fail closed. A compliance tag with **no** backing checker returns `UNBACKED`, and
`UNBACKED` is **blocking** - an unverifiable claim never becomes a silent pass. A checker that
raises is treated as a `BLOCK`.

The refusal is visible in the response, not buried: `POST /healthcare/disclosures` returns
**422** with the blocking findings when a disclosure exceeds minimum-necessary scope, lacks a
required authorization, or touches Part 2 records without consent - and the disclosure is never
persisted. `POST /lending/applications/{id}/underwrite` and `.../adverse-action` return **422**
with `blocking` on a gate failure. `POST /procurement/purchase-orders/{id}/approve` runs the
four-control chain (spend authorization, segregation of duties, three-way match, OFAC) and
returns **409** with the failing `gates`, leaving the PO unapproved.

Each department exposes gated AI agent actions - **every action route runs the full 7-gate
pipeline** (the ungated shortcut agents were removed), e.g.
`POST /engineering/pull-requests/{id}/review`, `POST /engineering/incidents/{id}/triage`,
`POST /engineering/deployments/{id}/assess` (always-HITL),
`POST /sales/opportunities/{id}/proposal` (always-HITL - customer documents never ship unreviewed),
`POST /support/tickets/{id}/auto-resolve` (always-HITL - customer responses get human review),
`POST /sales/accounts/{id}/churn-risk`, `POST /legal/contracts/{id}/review` (0.75 confidence -
pauses for approval; approving in the HITL queue resumes and executes it).

## Platform APIs

| Category | Prefix | Description |
|----------|--------|-------------|
| Auth | `/auth` | Login, user management, API key creation/revocation |
| Workforce | `/workforce` | Department mgmt, deployment, analytics, packs |
| Rules | `/rules` | Knowledge rules CRUD, validation, decay, provenance |
| Skills | `/skills` | Skill management, execution, confidence tracking |
| HITL | `/skills/hitl` + `/hitl` | ONE queue: `/skills/hitl/pending` lists every pending approval (incl. Gate-3 pipeline pauses, `route_type: GATED_AGENT`); approving a gate pause RESUMES the paused skill |
| Agents | `/agents` | `/blueprints`, `/deployed`, `/activity-feed`, `/debates/recent` |
| Executive | `/executive` | `/overview`, `/health`, `/predictions`, `/trust`, `/story` |
| Reality | `/reality` | `/twin` (org graph), `/shock`, `/provenance`, `/learning`, `/decision` - feed and shock outcomes are persisted and tenant-scoped; learning modifiers are derived from recorded severity, not hardcoded |
| Genome | `/genome` | `/state` - live trait scores compiled from real physics features |
| Evolution | `/evolution` | `/state` - enterprise fitness, 9 sub-scores, derived optimizations |
| BYOK Config | `/config` | `/llm-routing` (GET/POST/DELETE), `/llm-routing/{tier}/probe`, `/mcp-tools`, `/ontology`, `/federated`, `/autonomy` (GET, PUT per domain) |
| Billing | `/billing` | `/usage` (token metering + per-tier/model attribution), `/roi` (**safe autonomy rate**) |
| Metrics | `/metrics` | `/safe-autonomy` (computed live from logged executions), `/timeseries` (the **stored** rollup series: `metric`, `from`, `to`, `interval=hour\|day`; a metric with no stored samples returns an empty series with a note, never a fabricated 0 line), `/latency`, `/forecast` |
| Branding | `/branding` | GET (any authed tenant user, returns KAEOS defaults when unset) / PUT (admin) white-label theming |
| AI Foundry | `/foundry` | `/feedback`, `/datasets/build`, `/datasets`, `/datasets/export` (Phase 2); `/evolution/evaluate`, `/evolution/runs`, `/evolution/runs/{id}/promote` (Phase 3 - gated) |
| Agent Interface | `/mcp` + `/brain/skills-file` | MCP endpoint (JSON-RPC 2.0): `initialize`, `tools/list`, `tools/call` with 6 governed tools; Company Skills File export (markdown/json) |
| Privacy | `/privacy` | `/erasure` (GDPR Art.17, admin), `/retention` (GET/PUT), `/retention/apply` (configurable retention windows) |
| Infrastructure | `/infrastructure` | `/models`, `/prompts`, `/cost/telemetry`, `/agents/registry` |
| Pipeline | `/pipeline` | `/llm/providers`, `/connectors/available`, `/transforms/available`, `/run` |
| Dashboard | `/dashboard` | `/health`, `/cockpit`, `/ooda-events`, `/compliance` |
| Reports | `/reports` | `/health`, `/compliance` |
| Connectors | `/connectors` | `/providers` (catalog of all 22 ingestion adapters), list, health, feed, sync, credentials, schema-map |
| Extraction | `/extraction` | `/signals`, `/candidates` |
| Events | `/events` | `/log` - system event stream |
| Webhooks | `/webhooks` | Webhook subscription management |
| Conflicts | `/conflicts` | Cross-domain rule conflict arena |
| Marketplace | `/marketplace` | Domain pack & skill marketplace |
| Search | `/search` | Global full-text search |
| Chat | `/chat` | SSE streaming chat with context-aware agents |
| WebSocket | `/ws/{tenant_id}` | Real-time event feed (mounted bare, not under the API prefix) |

## Authorization tiers

Three distinct authorities, and they do not substitute for one another.

**1. Tenant identity (JWT or `X-Tenant-ID`) plus role.** Everything above. A tenant token proves
who a customer is; `require_role("viewer"|"operator"|"admin")` gates what they may do inside
their own tenant. Postgres RLS keeps the data tenant-scoped underneath.

**2. Platform super-admin (`X-Admin-Secret` header, checked against `ADMIN_SECRET`).**
Cross-tenant operations that a customer token must never authorize. Fails closed: **503** when
`ADMIN_SECRET` is unconfigured (the endpoint is disabled rather than falling back to a shared
default), **403** when the secret is wrong, compared in constant time.

| Surface | Prefix | Description |
|---------|--------|-------------|
| Operator console | `/ops` | `/tenants`, `/tenants/{id}`, `/overview`. Cross-tenant fleet view: plan and entitlements, rated usage, agent and execution counts, blended safe-autonomy rate, plan distribution. Declared on the router so a new `/ops` route cannot ship ungated; reads run on the owner/maintenance session, which is RLS-exempt by design. |
| API keys | `/admin/security/api-keys` | Bootstrap and revoke keys (mounted bare, not under the API prefix) |

The honesty contract holds here too: `blended_safe_autonomy_rate` is `null` with an explaining
`note` when no executions fall in the window, never a fabricated `0`.

**3. Public, unauthenticated.**

| Route | Description |
|-------|-------------|
| `GET /status` | Version, uptime, and reachability of `db` / `redis` / `llm`. Returns **503** when the database is unreachable so a load balancer can act on it. |
| `GET /health`, `GET /health/live` | Liveness probes |
| `GET /docs`, `GET /redoc`, `GET /openapi.json` | Interactive schema |

`/status` deliberately does **not** expose the platform safe-autonomy rate. It is a business
metric, and its cross-tenant aggregate is an unindexed full scan (`skill_executions` is indexed
tenant-id-leading), which would make an auth-free endpoint a denial-of-service amplifier. That
number lives on the super-admin-gated `/ops/overview` instead.
