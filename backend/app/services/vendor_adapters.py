"""
KAEOS — Vendor Adapter Catalog (live integrations)

Each adapter talks to a real vendor API and normalizes records into the Signal
shape the data fabric expects:
    {"external_id", "entity", "summary", "domain", "authority", "pii"}

Contract (matches app/services/live_connectors.py):
    test(config, secrets)  -> {"ok": bool, "detail": str}
    fetch(config, secrets) -> list[dict]

Adapters must FAIL GRACEFULLY: a bad credential returns {"ok": False, detail}
rather than raising, so a misconfigured connector never 500s the mesh.

`authority` encodes how much epistemic weight a source earns: systems of record
(HRIS, finance, incident systems) outrank chat and wiki content, which is
opinion as often as fact.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

import httpx

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = 20.0


def _fmt(d: Dict[str, Any], keys: int = 4) -> str:
    """Compact 'k=v, k=v' rendering for summaries."""
    return ", ".join(f"{k}={v}" for k, v in list(d.items())[:keys])


class _RestAdapter:
    """Shared plumbing: a GET against a vendor endpoint with adapter-defined auth."""
    domain = "general"
    entity = "record"
    authority = 0.8
    pii = False

    def headers(self, config, secrets) -> Dict[str, str]:
        return {"Accept": "application/json"}

    def auth(self, config, secrets):
        return None

    def base_url(self, config, secrets) -> str:
        raise NotImplementedError

    def test_path(self, config) -> str:
        raise NotImplementedError

    def fetch_path(self, config) -> str:
        raise NotImplementedError

    def fetch_params(self, config) -> Dict[str, Any]:
        return {}

    def extract(self, body: Any) -> List[Dict[str, Any]]:
        return body if isinstance(body, list) else []

    def to_signal(self, item: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "external_id": str(item.get("id", "")),
            "entity": self.entity,
            "summary": _fmt(item),
            "domain": self.domain,
            "authority": self.authority,
            "pii": self.pii,
        }

    def ok_detail(self, body: Any) -> str:
        return "Connected"

    async def test(self, config, secrets):
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, auth=self.auth(config, secrets)) as c:
            r = await c.get(
                f"{self.base_url(config, secrets).rstrip('/')}{self.test_path(config)}",
                headers=self.headers(config, secrets),
            )
            if 200 <= r.status_code < 300:
                try:
                    return {"ok": True, "detail": self.ok_detail(r.json())}
                except ValueError:
                    return {"ok": True, "detail": "Connected"}
            return {"ok": False,
                    "detail": f"{type(self).__name__} responded {r.status_code}: {r.text[:120]}"}

    async def fetch(self, config, secrets) -> List[Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, auth=self.auth(config, secrets)) as c:
            r = await c.get(
                f"{self.base_url(config, secrets).rstrip('/')}{self.fetch_path(config)}",
                headers=self.headers(config, secrets),
                params=self.fetch_params(config),
            )
            r.raise_for_status()
            body = r.json()
        items = self.extract(body)
        limit = int(config.get("batch_size", 25))
        return [self.to_signal(i) for i in items[:limit] if isinstance(i, dict)]


# ── Engineering & IT Ops ─────────────────────────────────────────────────────
# The largest slice of enterprise AI spend and, until now, the domain with no
# live integrations at all.

class GitHubAdapter(_RestAdapter):
    """GitHub REST v3 — pull requests for a repo. Auth: personal access token."""
    domain, entity, authority = "engineering", "pull_request", 0.9

    def headers(self, config, secrets):
        return {"Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {secrets.get('token', '')}",
                "X-GitHub-Api-Version": "2022-11-28"}

    def base_url(self, config, secrets):
        return config.get("api_url", "https://api.github.com")

    def test_path(self, config):
        return "/user"

    def fetch_path(self, config):
        return f"/repos/{config['owner']}/{config['repo']}/pulls"

    def fetch_params(self, config):
        return {"state": config.get("state", "open"), "per_page": config.get("batch_size", 25)}

    def ok_detail(self, body):
        return f"Authenticated as {body.get('login', 'user')}"

    def to_signal(self, pr):
        return {
            "external_id": str(pr.get("number", pr.get("id", ""))),
            "entity": "pull_request",
            "summary": f"PR #{pr.get('number')} {pr.get('title', '')} — "
                       f"{pr.get('state')} by {(pr.get('user') or {}).get('login', '?')}",
            "domain": self.domain, "authority": self.authority, "pii": False,
        }


class GitLabAdapter(_RestAdapter):
    """GitLab REST v4 — merge requests. Auth: PRIVATE-TOKEN."""
    domain, entity, authority = "engineering", "merge_request", 0.9

    def headers(self, config, secrets):
        return {"Accept": "application/json", "PRIVATE-TOKEN": secrets.get("token", "")}

    def base_url(self, config, secrets):
        return config.get("base_url", "https://gitlab.com")

    def test_path(self, config):
        return "/api/v4/user"

    def fetch_path(self, config):
        return f"/api/v4/projects/{config['project_id']}/merge_requests"

    def fetch_params(self, config):
        return {"state": config.get("state", "opened"), "per_page": config.get("batch_size", 25)}

    def ok_detail(self, body):
        return f"Authenticated as {body.get('username', 'user')}"

    def to_signal(self, mr):
        return {
            "external_id": str(mr.get("iid", mr.get("id", ""))),
            "entity": "merge_request",
            "summary": f"MR !{mr.get('iid')} {mr.get('title', '')} — {mr.get('state')}",
            "domain": self.domain, "authority": self.authority, "pii": False,
        }


class PagerDutyAdapter(_RestAdapter):
    """PagerDuty REST v2 — incidents. Auth: Token token=<key>."""
    domain, entity, authority = "engineering", "incident", 0.95

    def headers(self, config, secrets):
        return {"Accept": "application/vnd.pagerduty+json;version=2",
                "Authorization": f"Token token={secrets.get('api_key', '')}"}

    def base_url(self, config, secrets):
        return config.get("api_url", "https://api.pagerduty.com")

    def test_path(self, config):
        return "/abilities"

    def fetch_path(self, config):
        return "/incidents"

    def fetch_params(self, config):
        return {"limit": config.get("batch_size", 25),
                "statuses[]": config.get("status", "triggered"),
                "sort_by": "created_at:desc"}

    def extract(self, body):
        return body.get("incidents", [])

    def ok_detail(self, body):
        return f"Authenticated — {len(body.get('abilities', []))} abilities"

    def to_signal(self, i):
        return {
            "external_id": str(i.get("id", "")),
            "entity": "incident",
            "summary": f"[{i.get('incident_number')}] {i.get('title', '')} — "
                       f"{i.get('status')} urgency={i.get('urgency')} "
                       f"service={(i.get('service') or {}).get('summary', '?')}",
            "domain": self.domain, "authority": self.authority, "pii": False,
        }


class DatadogAdapter(_RestAdapter):
    """Datadog API v1 — monitors. Auth: DD-API-KEY + DD-APPLICATION-KEY."""
    domain, entity, authority = "engineering", "monitor", 0.9

    def headers(self, config, secrets):
        return {"Accept": "application/json",
                "DD-API-KEY": secrets.get("api_key", ""),
                "DD-APPLICATION-KEY": secrets.get("app_key", "")}

    def base_url(self, config, secrets):
        return config.get("site_url", "https://api.datadoghq.com")

    def test_path(self, config):
        return "/api/v1/validate"

    def fetch_path(self, config):
        return "/api/v1/monitor"

    def fetch_params(self, config):
        return {"page_size": config.get("batch_size", 25)}

    def ok_detail(self, body):
        return "API key valid" if body.get("valid") else "API key rejected"

    def to_signal(self, m):
        return {
            "external_id": str(m.get("id", "")),
            "entity": "monitor",
            "summary": f"Monitor '{m.get('name', '')}' — state={m.get('overall_state', '?')} "
                       f"type={m.get('type', '?')}",
            "domain": self.domain, "authority": self.authority, "pii": False,
        }


class SentryAdapter(_RestAdapter):
    """Sentry API v0 — unresolved issues. Auth: bearer auth token."""
    domain, entity, authority = "engineering", "error_issue", 0.85

    def headers(self, config, secrets):
        return {"Accept": "application/json",
                "Authorization": f"Bearer {secrets.get('token', '')}"}

    def base_url(self, config, secrets):
        return config.get("base_url", "https://sentry.io")

    def test_path(self, config):
        return f"/api/0/organizations/{config['organization']}/"

    def fetch_path(self, config):
        return f"/api/0/projects/{config['organization']}/{config['project']}/issues/"

    def fetch_params(self, config):
        return {"query": config.get("query", "is:unresolved"),
                "limit": config.get("batch_size", 25)}

    def ok_detail(self, body):
        return f"Org '{body.get('slug', '?')}' reachable"

    def to_signal(self, i):
        return {
            "external_id": str(i.get("id", "")),
            "entity": "error_issue",
            "summary": f"{i.get('title', '')} — {i.get('count', 0)} events, "
                       f"level={i.get('level', '?')}, culprit={i.get('culprit', '?')}",
            "domain": self.domain, "authority": self.authority, "pii": False,
        }


class ServiceNowAdapter(_RestAdapter):
    """ServiceNow Table API — incidents. Auth: basic."""
    domain, entity, authority = "operations", "incident", 0.95

    def auth(self, config, secrets):
        return (secrets.get("username", ""), secrets.get("password", ""))

    def base_url(self, config, secrets):
        return config["instance_url"]

    def test_path(self, config):
        return "/api/now/table/sys_user"

    def fetch_path(self, config):
        return f"/api/now/table/{config.get('table', 'incident')}"

    def fetch_params(self, config):
        return {"sysparm_limit": config.get("batch_size", 25),
                "sysparm_query": config.get("query", "ORDERBYDESCsys_created_on")}

    def extract(self, body):
        return body.get("result", [])

    def ok_detail(self, body):
        return "Instance reachable"

    def to_signal(self, r):
        return {
            "external_id": str(r.get("number", r.get("sys_id", ""))),
            "entity": "incident",
            "summary": f"[{r.get('number', '?')}] {r.get('short_description', '')} — "
                       f"state={r.get('state', '?')} priority={r.get('priority', '?')}",
            "domain": self.domain, "authority": self.authority, "pii": False,
        }


# ── Support ──────────────────────────────────────────────────────────────────

class ZendeskAdapter(_RestAdapter):
    """Zendesk API v2 — tickets. Auth: '{email}/token' + API token."""
    domain, entity, authority, pii = "support", "ticket", 0.9, True

    def auth(self, config, secrets):
        return (f"{secrets.get('email', '')}/token", secrets.get("api_token", ""))

    def base_url(self, config, secrets):
        return config["subdomain_url"]

    def test_path(self, config):
        return "/api/v2/users/me.json"

    def fetch_path(self, config):
        return "/api/v2/tickets.json"

    def fetch_params(self, config):
        return {"per_page": config.get("batch_size", 25), "sort_order": "desc"}

    def extract(self, body):
        return body.get("tickets", [])

    def ok_detail(self, body):
        return f"Authenticated as {(body.get('user') or {}).get('name', 'user')}"

    def to_signal(self, t):
        return {
            "external_id": str(t.get("id", "")),
            "entity": "ticket",
            "summary": f"#{t.get('id')} {t.get('subject', '')} — status={t.get('status')} "
                       f"priority={t.get('priority', '?')}",
            "domain": self.domain, "authority": self.authority, "pii": True,
        }


class IntercomAdapter(_RestAdapter):
    """Intercom API — conversations. Auth: bearer access token."""
    domain, entity, authority, pii = "support", "conversation", 0.85, True

    def headers(self, config, secrets):
        return {"Accept": "application/json",
                "Authorization": f"Bearer {secrets.get('access_token', '')}",
                "Intercom-Version": config.get("api_version", "2.11")}

    def base_url(self, config, secrets):
        return config.get("api_url", "https://api.intercom.io")

    def test_path(self, config):
        return "/me"

    def fetch_path(self, config):
        return "/conversations"

    def fetch_params(self, config):
        return {"per_page": config.get("batch_size", 25)}

    def extract(self, body):
        return body.get("conversations", [])

    def ok_detail(self, body):
        return f"Workspace {body.get('app', {}).get('name', '?')} reachable"

    def to_signal(self, c):
        return {
            "external_id": str(c.get("id", "")),
            "entity": "conversation",
            "summary": f"Conversation {c.get('id')} — state={c.get('state', '?')} "
                       f"open={c.get('open')} priority={c.get('priority', '?')}",
            "domain": self.domain, "authority": self.authority, "pii": True,
        }


# ── Sales ────────────────────────────────────────────────────────────────────

class HubSpotAdapter(_RestAdapter):
    """HubSpot CRM v3 — deals. Auth: private app bearer token."""
    domain, entity, authority = "sales", "deal", 0.9

    def headers(self, config, secrets):
        return {"Accept": "application/json",
                "Authorization": f"Bearer {secrets.get('access_token', '')}"}

    def base_url(self, config, secrets):
        return config.get("api_url", "https://api.hubapi.com")

    def test_path(self, config):
        return "/crm/v3/objects/deals"

    def fetch_path(self, config):
        return f"/crm/v3/objects/{config.get('object_type', 'deals')}"

    def fetch_params(self, config):
        return {"limit": config.get("batch_size", 25),
                "properties": config.get("properties", "dealname,dealstage,amount,closedate")}

    def extract(self, body):
        return body.get("results", [])

    def ok_detail(self, body):
        return f"CRM reachable — {len(body.get('results', []))} deals visible"

    def to_signal(self, d):
        p = d.get("properties", {})
        return {
            "external_id": str(d.get("id", "")),
            "entity": "deal",
            "summary": f"{p.get('dealname', 'deal')} — stage={p.get('dealstage', '?')} "
                       f"amount={p.get('amount', '?')} close={p.get('closedate', '?')}",
            "domain": self.domain, "authority": self.authority, "pii": False,
        }


# ── HR ───────────────────────────────────────────────────────────────────────

class BambooHRAdapter(_RestAdapter):
    """BambooHR API v1 — employee directory. Auth: basic (api_key:x)."""
    domain, entity, authority, pii = "hr", "employee", 0.95, True

    def auth(self, config, secrets):
        return (secrets.get("api_key", ""), "x")

    def base_url(self, config, secrets):
        return f"https://api.bamboohr.com/api/gateway.php/{config['subdomain']}"

    def test_path(self, config):
        return "/v1/employees/directory"

    def fetch_path(self, config):
        return "/v1/employees/directory"

    def extract(self, body):
        return body.get("employees", [])

    def ok_detail(self, body):
        return f"Directory reachable — {len(body.get('employees', []))} employees"

    def to_signal(self, e):
        return {
            "external_id": str(e.get("id", "")),
            "entity": "employee",
            "summary": f"{e.get('displayName', '')} — {e.get('jobTitle', '?')} "
                       f"in {e.get('department', '?')}",
            "domain": self.domain, "authority": self.authority, "pii": True,
        }


class GreenhouseAdapter(_RestAdapter):
    """Greenhouse Harvest API — candidates. Auth: basic (api_key:'')."""
    domain, entity, authority, pii = "hr", "candidate", 0.9, True

    def auth(self, config, secrets):
        return (secrets.get("api_key", ""), "")

    def base_url(self, config, secrets):
        return config.get("api_url", "https://harvest.greenhouse.io")

    def test_path(self, config):
        return "/v1/users"

    def fetch_path(self, config):
        return "/v1/candidates"

    def fetch_params(self, config):
        return {"per_page": config.get("batch_size", 25)}

    def ok_detail(self, body):
        return f"Harvest API reachable — {len(body) if isinstance(body, list) else 0} users"

    def to_signal(self, c):
        apps = c.get("applications") or []
        stage = (apps[0].get("current_stage") or {}).get("name", "?") if apps else "?"
        return {
            "external_id": str(c.get("id", "")),
            "entity": "candidate",
            "summary": f"{c.get('first_name', '')} {c.get('last_name', '')} — stage={stage}",
            "domain": self.domain, "authority": self.authority, "pii": True,
        }


# ── Finance ──────────────────────────────────────────────────────────────────

class StripeAdapter(_RestAdapter):
    """Stripe API — invoices. Auth: secret key bearer."""
    domain, entity, authority = "finance", "invoice", 0.95

    def headers(self, config, secrets):
        return {"Accept": "application/json",
                "Authorization": f"Bearer {secrets.get('secret_key', '')}"}

    def base_url(self, config, secrets):
        return config.get("api_url", "https://api.stripe.com")

    def test_path(self, config):
        return "/v1/balance"

    def fetch_path(self, config):
        return f"/v1/{config.get('resource', 'invoices')}"

    def fetch_params(self, config):
        return {"limit": config.get("batch_size", 25)}

    def extract(self, body):
        return body.get("data", [])

    def ok_detail(self, body):
        return f"Account reachable — livemode={body.get('livemode')}"

    def to_signal(self, i):
        total = i.get("total")
        amount = f"{total / 100:.2f}" if isinstance(total, int) else "?"
        return {
            "external_id": str(i.get("id", "")),
            "entity": "invoice",
            "summary": f"Invoice {i.get('number') or i.get('id')} — status={i.get('status', '?')} "
                       f"amount={amount} {str(i.get('currency', '')).upper()}",
            "domain": self.domain, "authority": self.authority, "pii": False,
        }


# ── Legal ────────────────────────────────────────────────────────────────────

class DocuSignAdapter(_RestAdapter):
    """DocuSign eSignature REST v2.1 — envelopes. Auth: OAuth bearer token."""
    domain, entity, authority, pii = "legal", "envelope", 0.9, True

    def headers(self, config, secrets):
        return {"Accept": "application/json",
                "Authorization": f"Bearer {secrets.get('access_token', '')}"}

    def base_url(self, config, secrets):
        return config["base_uri"]

    def test_path(self, config):
        return f"/restapi/v2.1/accounts/{config['account_id']}"

    def fetch_path(self, config):
        return f"/restapi/v2.1/accounts/{config['account_id']}/envelopes"

    def fetch_params(self, config):
        return {"from_date": config.get("from_date", "2024-01-01"),
                "count": config.get("batch_size", 25)}

    def extract(self, body):
        return body.get("envelopes", [])

    def ok_detail(self, body):
        return f"Account '{body.get('accountName', '?')}' reachable"

    def to_signal(self, e):
        return {
            "external_id": str(e.get("envelopeId", "")),
            "entity": "envelope",
            "summary": f"Envelope '{e.get('emailSubject', '')}' — status={e.get('status', '?')} "
                       f"sent={e.get('sentDateTime', '?')}",
            "domain": self.domain, "authority": self.authority, "pii": True,
        }


# ── Collaboration / knowledge (every enterprise has these) ───────────────────

class SlackAdapter(_RestAdapter):
    """
    Slack Web API — channel history. Auth: bot token.

    Authority is deliberately low: chat is where decisions are *discussed*, not
    where they are recorded. Treating Slack talk as fact is how a knowledge base
    fills with confident nonsense.
    """
    domain, entity, authority, pii = "general", "message", 0.5, True

    def headers(self, config, secrets):
        return {"Accept": "application/json",
                "Authorization": f"Bearer {secrets.get('bot_token', '')}"}

    def base_url(self, config, secrets):
        return "https://slack.com"

    def test_path(self, config):
        return "/api/auth.test"

    def fetch_path(self, config):
        return "/api/conversations.history"

    def fetch_params(self, config):
        return {"channel": config.get("channel_id", ""), "limit": config.get("batch_size", 25)}

    def extract(self, body):
        # Slack returns HTTP 200 with ok:false on auth errors.
        if not body.get("ok"):
            raise httpx.HTTPError(f"Slack API error: {body.get('error', 'unknown')}")
        return body.get("messages", [])

    async def test(self, config, secrets):
        result = await super().test(config, secrets)
        return result

    def ok_detail(self, body):
        if not body.get("ok"):
            return f"Slack rejected the token: {body.get('error', 'unknown')}"
        return f"Authenticated as {body.get('user', '?')} in {body.get('team', '?')}"

    def to_signal(self, m):
        text = (m.get("text") or "").replace("\n", " ")
        return {
            "external_id": str(m.get("ts", "")),
            "entity": "message",
            "summary": f"Slack message from {m.get('user', '?')}: {text[:140]}",
            "domain": self.domain, "authority": self.authority, "pii": True,
        }


class ConfluenceAdapter(_RestAdapter):
    """Confluence Cloud REST — pages. Auth: email + API token basic."""
    domain, entity, authority = "general", "page", 0.75

    def auth(self, config, secrets):
        return (secrets.get("email", ""), secrets.get("api_token", ""))

    def base_url(self, config, secrets):
        return config["base_url"]

    def test_path(self, config):
        return "/wiki/rest/api/space"

    def fetch_path(self, config):
        return "/wiki/rest/api/content"

    def fetch_params(self, config):
        params = {"limit": config.get("batch_size", 25), "type": "page"}
        if config.get("space_key"):
            params["spaceKey"] = config["space_key"]
        return params

    def extract(self, body):
        return body.get("results", [])

    def ok_detail(self, body):
        return f"Confluence reachable — {len(body.get('results', []))} spaces"

    def to_signal(self, p):
        return {
            "external_id": str(p.get("id", "")),
            "entity": "page",
            "summary": f"Confluence page '{p.get('title', '')}' "
                       f"(space {(p.get('space') or {}).get('key', '?')})",
            "domain": self.domain, "authority": self.authority, "pii": False,
        }


class NotionAdapter(_RestAdapter):
    """Notion API — search. Auth: integration token. Uses POST, so overrides fetch."""
    domain, entity, authority = "general", "page", 0.7

    def headers(self, config, secrets):
        return {"Accept": "application/json",
                "Authorization": f"Bearer {secrets.get('token', '')}",
                "Notion-Version": config.get("api_version", "2022-06-28"),
                "Content-Type": "application/json"}

    def base_url(self, config, secrets):
        return "https://api.notion.com"

    def test_path(self, config):
        return "/v1/users/me"

    def fetch_path(self, config):
        return "/v1/search"

    def ok_detail(self, body):
        return f"Integration '{body.get('name', '?')}' authorized"

    async def fetch(self, config, secrets) -> List[Dict[str, Any]]:
        payload: Dict[str, Any] = {"page_size": int(config.get("batch_size", 25))}
        if config.get("query"):
            payload["query"] = config["query"]
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
            r = await c.post("https://api.notion.com/v1/search",
                             headers=self.headers(config, secrets), json=payload)
            r.raise_for_status()
            body = r.json()
        out = []
        for item in body.get("results", []):
            title = "untitled"
            props = item.get("properties") or {}
            for prop in props.values():
                if prop.get("type") == "title" and prop.get("title"):
                    title = prop["title"][0].get("plain_text", "untitled")
                    break
            out.append({
                "external_id": str(item.get("id", "")),
                "entity": item.get("object", "page"),
                "summary": f"Notion {item.get('object', 'page')} '{title}'",
                "domain": self.domain, "authority": self.authority, "pii": False,
            })
        return out


class MicrosoftGraphAdapter(_RestAdapter):
    """Microsoft Graph — mail/Teams/SharePoint. Auth: OAuth bearer token."""
    domain, entity, authority, pii = "general", "message", 0.6, True

    def headers(self, config, secrets):
        return {"Accept": "application/json",
                "Authorization": f"Bearer {secrets.get('access_token', '')}"}

    def base_url(self, config, secrets):
        return config.get("api_url", "https://graph.microsoft.com")

    def test_path(self, config):
        return "/v1.0/me"

    def fetch_path(self, config):
        return f"/v1.0/{config.get('resource', 'me/messages')}"

    def fetch_params(self, config):
        return {"$top": config.get("batch_size", 25)}

    def extract(self, body):
        return body.get("value", [])

    def ok_detail(self, body):
        return f"Authenticated as {body.get('displayName') or body.get('userPrincipalName', 'user')}"

    def to_signal(self, m):
        subject = m.get("subject") or m.get("displayName") or m.get("name") or "item"
        sender = ((m.get("from") or {}).get("emailAddress") or {}).get("address", "?")
        return {
            "external_id": str(m.get("id", "")),
            "entity": self.entity,
            "summary": f"Graph item '{subject}' from {sender}",
            "domain": self.domain, "authority": self.authority, "pii": True,
        }


# ── Registry ─────────────────────────────────────────────────────────────────

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
