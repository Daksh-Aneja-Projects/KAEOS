from __future__ import annotations

from .devops import GitHubAdapter, GitLabAdapter, PagerDutyAdapter, DatadogAdapter, SentryAdapter
from .itsm import ServiceNowAdapter, ZendeskAdapter, IntercomAdapter, HubSpotAdapter
from .hr_finance import BambooHRAdapter, GreenhouseAdapter, StripeAdapter, DocuSignAdapter
from .collaboration import SlackAdapter, ConfluenceAdapter, NotionAdapter, MicrosoftGraphAdapter
from .bespoke_bridge import BESPOKE_ADAPTERS


VENDOR_ADAPTERS = {
    # Engineering & IT Ops
    "github": GitHubAdapter(),
    "gitlab": GitLabAdapter(),
    "pagerduty": PagerDutyAdapter(),
    "datadog": DatadogAdapter(),
    "sentry": SentryAdapter(),
    "servicenow": ServiceNowAdapter(),
    # Support
    "zendesk": ZendeskAdapter(),
    "intercom": IntercomAdapter(),
    # Sales
    "hubspot": HubSpotAdapter(),
    # HR
    "bamboohr": BambooHRAdapter(),
    "greenhouse": GreenhouseAdapter(),
    # Finance
    "stripe": StripeAdapter(),
    # Legal
    "docusign": DocuSignAdapter(),
    # Collaboration
    "slack": SlackAdapter(),
    "confluence": ConfluenceAdapter(),
    "notion": NotionAdapter(),
    "microsoft_graph": MicrosoftGraphAdapter(),
    # Per-department bespoke connectors bridged into the pull catalog (M8/M15):
    # finance accounting (QuickBooks/Xero/NetSuite), engineering issue tracker,
    # healthcare EHR. Pull-ready + credential-gated; validate against the vendor
    # sandbox before trusting the data (see KNOWN_LIMITATIONS).
    **BESPOKE_ADAPTERS,
}

VENDOR_REQUIRED_CONFIG = {
    "github": ["owner", "repo"],
    "gitlab": ["project_id"],
    "pagerduty": [],
    "datadog": [],
    "sentry": ["organization", "project"],
    "servicenow": ["instance_url"],
    "zendesk": ["subdomain_url"],
    "intercom": [],
    "hubspot": [],
    "bamboohr": ["subdomain"],
    "greenhouse": [],
    "stripe": [],
    "docusign": ["base_uri", "account_id"],
    "slack": ["channel_id"],
    "confluence": ["base_url"],
    "notion": [],
    "microsoft_graph": [],
    # Bridged bespoke connectors validate their own credentials at construction
    # (the bridge catches and fails gracefully), so no pre-store required_config.
    "quickbooks": [],
    "xero": [],
    "netsuite_accounting": [],
    "issue_tracker": [],
    "ehr": [],
    "coupa": [],
    "ariba": [],
    "netsuite_procurement": [],
}

# Name fragments → provider, for inference from a connector's display name.
VENDOR_NAME_HINTS = {
    "github": "github", "git hub": "github",
    "gitlab": "gitlab",
    "pagerduty": "pagerduty", "pager duty": "pagerduty", "on-call": "pagerduty",
    "alerting": "pagerduty", "paging": "pagerduty",
    "datadog": "datadog", "data dog": "datadog", "monitoring": "datadog",
    "observability": "datadog",
    "sentry": "sentry", "error tracking": "sentry",
    "servicenow": "servicenow", "service now": "servicenow", "itsm": "servicenow",
    "zendesk": "zendesk", "helpdesk": "zendesk", "help desk": "zendesk",
    "intercom": "intercom",
    "hubspot": "hubspot", "hub spot": "hubspot",
    "bamboo": "bamboohr", "bamboohr": "bamboohr",
    "greenhouse": "greenhouse", "recruiting": "greenhouse", "ats": "greenhouse",
    "stripe": "stripe", "payments": "stripe",
    "docusign": "docusign", "e-signature": "docusign", "esignature": "docusign",
    "slack": "slack",
    "confluence": "confluence", "wiki": "confluence",
    "notion": "notion",
    "microsoft graph": "microsoft_graph", "outlook": "microsoft_graph",
    "teams": "microsoft_graph", "sharepoint": "microsoft_graph", "o365": "microsoft_graph",
    "productivity suite": "microsoft_graph", "code repository": "github",
}
