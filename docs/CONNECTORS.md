# Live Enterprise Integrations (self-service)

Back to the [README](../README.md). Related: [API reference](API.md) |
[Security model](SECURITY_MODEL.md)

Every tenant connects their own systems from the **Integrations** page - no engineering
involvement. Click the key icon on any connector, paste your credentials, test, and sync:

**22 live ingestion adapters** across every domain. `GET /connectors/providers` returns the
machine-readable catalog (id, domain, authority weight, PII flag, required config).

**Write-back scope (honest):** pushing governed changes back INTO the external system is
implemented for **six** targets (see [Write-back](#write-back) below). Every other adapter is
read/sync-only, and a write attempt against one returns
`"no write-back adapter for provider '<id>'"` rather than pretending. Governed writes to targets
without an adapter land in KAEOS's internal governed object store (reversible, drift-monitored)
until their adapters ship. See [Known Limitations](KNOWN_LIMITATIONS.md).

| Domain | Provider | Auth | What syncs |
|--------|----------|------|-----------|
| **Engineering** | **GitHub** | Personal access token | Pull requests for a repo |
| | **GitLab** | Private token | Merge requests for a project |
| | **Jira Cloud** | Email + API token | Recently updated issues (JQL-configurable) |
| | **PagerDuty** | API key | Incidents (status-filterable) |
| | **Datadog** | API key + app key | Monitors and their alert state |
| | **Sentry** | Auth token | Unresolved error issues |
| **IT Ops** | **ServiceNow** | Basic auth | Any table - incidents, changes, CMDB |
| **Support** | **Zendesk** | Email + API token | Tickets |
| | **Intercom** | Access token | Conversations |
| **Sales** | **Salesforce** | Connected-app OAuth or access token | Opportunities (SOQL-configurable) |
| | **HubSpot** | Private app token | Deals (any CRM object) |
| **HR** | **Workday** | ISU account (RaaS report URL) | Worker records from any RaaS report |
| | **BambooHR** | API key | Employee directory |
| | **Greenhouse** | Harvest API key | Candidates and pipeline stage |
| **Finance** | **SAP** | OData basic auth or API key | Any OData entity set (invoices, vendors...) |
| | **Stripe** | Secret key | Invoices, charges, any resource |
| **Legal** | **DocuSign** | OAuth token | Envelopes and signature status |
| **Collaboration** | **Slack** | Bot token | Channel history |
| | **Confluence** | Email + API token | Pages by space |
| | **Notion** | Integration token | Pages and databases |
| | **Microsoft Graph** | OAuth token | Mail, Teams, SharePoint |
| **Any** | **Generic REST** | Bearer token / API key / none | Any JSON endpoint |

## Write-back

Six of those adapters also push governed changes back out.

| Write-back target | API used | Scope | Idempotent create |
|-------------------|----------|-------|-------------------|
| **ServiceNow** | Table API (`incident`, `task`, `sc_task`, `problem`, `change_request`) | create, update by `sys_id`, delete | Yes, on ServiceNow's native `correlation_id`, probed before create |
| **Zendesk** | API v2 tickets | create, update, delete | Yes, on the ticket's native `external_id`, searched before create |
| **Jira Cloud** | REST v3 issues | create, field update, delete | Yes, via a `kaeos-<idem>` label found by JQL before create |
| **Slack** | `chat.postMessage` | post a message to a channel | No. `chat.postMessage` is append-only with no server-side idempotency; the token is stamped into message metadata for downstream dedup |
| **Salesforce** | sObject REST (`Account`, `Opportunity`) | create, update by id | Yes, via a `[kaeos:<idem>]` marker in `Description` found by a SOQL probe before create |
| **Generic REST** | `POST {base_url}/kaeos/sync` | any entity the receiving endpoint accepts | `Idempotency-Key` header, honoured by the receiver |

**Why the idempotency probes matter.** A create whose HTTP response is lost looks identical to a
create that never happened, so a blind retry duplicates the record. Each adapter above stamps its
idempotency token on a field the target system indexes natively and queries for it first: the retry
finds the existing record and reports success instead of creating a twin.

**Workday write-back is an honest failure state, not a silent one.** Real Workday writes need a
customer Workday tenant plus ISU credentials and there is no public sandbox, so the adapter returns
a message saying exactly that until those are configured.

**Queue semantics.** Governed mutations are queued as outbound writes and dispatched with retry.
Each write is isolated: an adapter that raises fails only its own row, never the batch. After 5
attempts a write becomes `DEAD`, which is terminal, so a poison row cannot sit at the head of the
queue and block every other tenant's write-backs. Dispatch runs on the owner maintenance session
because the scheduled sweep has no request context and, under Postgres RLS, a tenant-less app-role
session would match zero rows; isolation is preserved by filtering connectors on each write's own
tenant.

**Known ceiling on Jira.** A Jira *status* change is a POST to the `/transitions` endpoint rather
than a field write, so the adapter handles fields only. A governed status move needs a transitions
call that is not built yet.

## Authority weighting

**Sources are not equally trusted.** Each adapter carries an `authority` weight that flows into
confidence scoring: systems of record (BambooHR 0.95, PagerDuty 0.95, Stripe 0.95) outrank wiki
content (Confluence 0.75) which outranks chat (Slack 0.5). Slack is where decisions get *discussed*;
treating that talk as fact is how a knowledge base fills with confident nonsense.

## PII handling

Adapters touching personal data are flagged `handles_pii`; the ingest pipeline applies PII
scrubbing as records are normalized into Signals. Keeping PII out of *cloud* LLMs is a separate
concern with its own controls: a data-residency mode (`DATA_RESIDENCY` pins inference to a local
Ollama-only model and strips every cloud credential/endpoint) and pre-egress PII scrubbing on
outbound LLM calls. Both are live: every **cloud** LLM call is scrubbed by default - belt-and-
suspenders, Presidio NER (names/contextual PII) plus a deterministic structured backstop that
removes email/phone/SSN/credit-card/IP/IBAN even when Presidio is absent or under-confident -
while **local** Ollama calls stay in-region and unscrubbed.
Verified by `tests/test_pii_egress.py`.

## Security model

- **Secrets are write-only.** They are sent once over the authenticated HTTPS channel,
  encrypted at rest (Fernet, keyed from `SECRET_KEY`), and the API only ever returns
  secret **key names** - never values. Nothing sensitive renders back into the UI.
- **Admin-gated and tenant-scoped.** Storing/deleting credentials requires the tenant's
  admin role; credentials are isolated per tenant like all other data.
- **Graceful fallback.** Connectors without credentials keep serving the deterministic
  demo feed, so evaluation environments work with zero setup.
- **Tenant-supplied URLs cannot reach internal hosts.** Every outbound adapter call goes
  through a guarded HTTP client that pins the connect-time IP (defeating DNS rebinding) and
  refuses redirects, so an `instance_url` or `base_url` a tenant controls cannot be pointed at
  a cloud metadata service or an internal address.

## Flow

`PUT /connectors/{id}/credentials` -> `POST /connectors/{id}/test` ->
`POST /connectors/{id}/connect` -> `POST /connectors/{id}/sync` (mode `LIVE`), with every
pulled record normalized into a Signal feeding the Company Brain.
