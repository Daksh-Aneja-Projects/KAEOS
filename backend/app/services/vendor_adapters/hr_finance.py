from __future__ import annotations



from .base import _RestAdapter


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
            "summary": f"{e.get('displayName', '')} - {e.get('jobTitle', '?')} "
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
            "summary": f"{c.get('first_name', '')} {c.get('last_name', '')} - stage={stage}",
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
            "summary": f"Invoice {i.get('number') or i.get('id')} - status={i.get('status', '?')} "
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
            "summary": f"Envelope '{e.get('emailSubject', '')}' - status={e.get('status', '?')} "
                       f"sent={e.get('sentDateTime', '?')}",
            "domain": self.domain, "authority": self.authority, "pii": True,
        }


# ── Collaboration / knowledge (every enterprise has these) ───────────────────
