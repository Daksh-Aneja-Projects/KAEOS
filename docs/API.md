# API Reference

Back to the [README](../README.md). Related: [Architecture](ARCHITECTURE.md) |
[Connectors](CONNECTORS.md) | [Security model](SECURITY_MODEL.md)

All endpoints are documented at `http://localhost:8001/docs` (Swagger UI).

## Department APIs (all require `X-Tenant-ID` or JWT)

| Department | Prefix | Key Endpoints |
|-----------|--------|---------------|
| HR | `/hr` | `/employees`, `/requisitions`, `/candidates`, `/time-off-requests`, `/performance-reviews` |
| Finance | `/finance` | `/invoices`, `/vendors`, `/budgets`, `/forecasts`, `/tax/filings`, `/sox-controls` |
| Legal | `/legal` | `/matters`, `/contracts`, `/compliance/obligations`, `/cases`, `/privacy/dsars` |
| Sales | `/sales` | `/leads`, `/accounts`, `/opportunities`, `/forecasts` |
| Support | `/support` | `/tickets`, `/kb/articles`, `/csat/surveys`, `/sla/metrics` |
| Operations | `/operations` | `/projects`, `/resources`, `/vendors`, `/procurements`, `/inspections` |
| Engineering | `/engineering` | `/services`, `/engineers`, `/pull-requests`, `/deployments`, `/incidents`, `/postmortems`, `/dashboard` |

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
| BYOK Config | `/config` | `/llm-routing` (GET/POST/DELETE), `/llm-routing/{tier}/probe`, `/mcp-tools`, `/ontology`, `/federated` |
| Billing | `/billing` | `/usage` (token metering + per-tier/model attribution), `/roi` (**safe autonomy rate**) |
| AI Foundry | `/foundry` | `/feedback`, `/datasets/build`, `/datasets`, `/datasets/export` (Phase 2); `/evolution/evaluate`, `/evolution/runs`, `/evolution/runs/{id}/promote` (Phase 3 - gated) |
| Agent Interface | `/mcp` + `/brain/skills-file` | MCP endpoint (JSON-RPC 2.0): `initialize`, `tools/list`, `tools/call` with 6 governed tools; Company Skills File export (markdown/json) |
| Privacy | `/privacy` | `/erasure` (GDPR Art.17, admin), `/retention` (GET/PUT), `/retention/apply` (configurable retention windows) |
| Infrastructure | `/infrastructure` | `/models`, `/prompts`, `/cost/telemetry`, `/agents/registry` |
| Pipeline | `/pipeline` | `/llm/providers`, `/connectors/available`, `/transforms/available`, `/run` |
| Dashboard | `/dashboard` | `/health`, `/cockpit`, `/ooda-events`, `/compliance` |
| Reports | `/reports` | `/health`, `/compliance` |
| Connectors | `/connectors` | `/providers` (catalog of all 22 live adapters), list, health, feed, sync, credentials, schema-map |
| Extraction | `/extraction` | `/signals`, `/candidates` |
| Events | `/events` | `/log` - system event stream |
| Webhooks | `/webhooks` | Webhook subscription management |
| Conflicts | `/conflicts` | Cross-domain rule conflict arena |
| Marketplace | `/marketplace` | Domain pack & skill marketplace |
| Search | `/search` | Global full-text search |
| Chat | `/chat` | SSE streaming chat with context-aware agents |
| WebSocket | `/ws/{tenant_id}` | Real-time event feed |
