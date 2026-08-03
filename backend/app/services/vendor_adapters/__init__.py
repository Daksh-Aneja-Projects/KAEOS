"""KAEOS — Vendor Adapter Catalog (live integrations).

Package split by vendor category (base / devops / itsm / hr_finance /
collaboration / registry). This barrel re-exports the public surface so
`from app.services.vendor_adapters import VENDOR_ADAPTERS` keeps working.
"""
from .base import _RestAdapter, _fmt, HTTP_TIMEOUT  # noqa: F401
from .devops import GitHubAdapter, GitLabAdapter, PagerDutyAdapter, DatadogAdapter, SentryAdapter  # noqa: F401
from .itsm import ServiceNowAdapter, ZendeskAdapter, IntercomAdapter, HubSpotAdapter  # noqa: F401
from .hr_finance import BambooHRAdapter, GreenhouseAdapter, StripeAdapter, DocuSignAdapter  # noqa: F401
from .collaboration import SlackAdapter, ConfluenceAdapter, NotionAdapter, MicrosoftGraphAdapter  # noqa: F401
from .registry import VENDOR_ADAPTERS, VENDOR_REQUIRED_CONFIG, VENDOR_NAME_HINTS  # noqa: F401
