# Live Enterprise Integrations (self-service)

Back to the [README](../README.md). Related: [API reference](API.md) |
[Security model](SECURITY_MODEL.md)

Every tenant connects their own systems from the **Integrations** page - no engineering
involvement. Click the key icon on any connector, paste your credentials, test, and sync:

**22 live adapters** across every domain. `GET /connectors/providers` returns the machine-readable
catalog (id, domain, authority weight, PII flag, required config).

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

## Flow

`PUT /connectors/{id}/credentials` -> `POST /connectors/{id}/test` ->
`POST /connectors/{id}/connect` -> `POST /connectors/{id}/sync` (mode `LIVE`), with every
pulled record normalized into a Signal feeding the Company Brain.
