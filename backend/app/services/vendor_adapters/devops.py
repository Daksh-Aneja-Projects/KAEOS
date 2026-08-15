from __future__ import annotations



from .base import _RestAdapter


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
            "summary": f"PR #{pr.get('number')} {pr.get('title', '')} - "
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
            "summary": f"MR !{mr.get('iid')} {mr.get('title', '')} - {mr.get('state')}",
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
            "summary": f"[{i.get('incident_number')}] {i.get('title', '')} - "
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
            "summary": f"Monitor '{m.get('name', '')}' - state={m.get('overall_state', '?')} "
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
            "summary": f"{i.get('title', '')} - {i.get('count', 0)} events, "
                       f"level={i.get('level', '?')}, culprit={i.get('culprit', '?')}",
            "domain": self.domain, "authority": self.authority, "pii": False,
        }
