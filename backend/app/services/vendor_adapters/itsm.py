from __future__ import annotations



from .base import _RestAdapter


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
