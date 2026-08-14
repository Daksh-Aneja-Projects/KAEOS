from __future__ import annotations

from typing import Any, Dict, List

import httpx
from app.core.outbound import guarded_async_client

from .base import _RestAdapter, HTTP_TIMEOUT


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
        async with guarded_async_client(timeout=HTTP_TIMEOUT) as c:
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
