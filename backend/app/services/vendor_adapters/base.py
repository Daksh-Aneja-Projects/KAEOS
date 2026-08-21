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

from app.core.outbound import guarded_async_client

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = 20.0


def _fmt(d: Dict[str, Any], keys: int = 4) -> str:
    """Compact 'k=v, k=v' rendering for summaries."""
    return ", ".join(f"{k}={v}" for k, v in list(d.items())[:keys])


class _RestAdapter:
    """Shared plumbing: a GET against a vendor endpoint with adapter-defined auth.

    Abstract base of the template-method pattern: ``base_url``/``test_path``/
    ``fetch_path`` raise NotImplementedError and MUST be overridden by each
    concrete vendor adapter below. They are contract markers, not dead code.
    """
    domain = "general"
    entity = "record"
    authority = 0.8
    pii = False
    # M15: the record field carrying the source's OWN last-update time. When set,
    # fetch() surfaces it as ``updated_at`` so the scheduler advances the delta
    # cursor from the source's clock (never KAEOS's wall clock). Left None ->
    # no watermark, an honest fixed-window pull.
    updated_at_field: str | None = None

    def cursor_params(self, config) -> Dict[str, Any]:
        """M15: incremental-pull query params derived from ``config['_cursor']``
        (the watermark of the newest record seen last sync). Default: none — a
        fixed-window pull that re-reads the most-recent window each pass, so
        changes beyond ``batch_size`` are re-fetched rather than paged past.
        Override to fetch ONLY records changed since the watermark; ServiceNow and
        Stripe do. Adding it to another adapter is a small, endpoint-preserving
        change, best validated against that vendor's sandbox."""
        return {}

    def _stamp_watermark(self, signal: Dict[str, Any], item: Dict[str, Any]) -> Dict[str, Any]:
        """Attach ``updated_at`` from ``updated_at_field`` (M15). No-op unless the
        adapter declares the field; never overwrites an explicit value."""
        if self.updated_at_field:
            wm = item.get(self.updated_at_field)
            if wm is not None:
                signal.setdefault("updated_at", wm)
        return signal

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
        async with guarded_async_client(timeout=HTTP_TIMEOUT, auth=self.auth(config, secrets)) as c:
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
        async with guarded_async_client(timeout=HTTP_TIMEOUT, auth=self.auth(config, secrets)) as c:
            r = await c.get(
                f"{self.base_url(config, secrets).rstrip('/')}{self.fetch_path(config)}",
                headers=self.headers(config, secrets),
                # M15: incremental filter (if the adapter defines one) rides on the
                # same GET as the base params.
                params={**self.fetch_params(config), **self.cursor_params(config)},
            )
            r.raise_for_status()
            body = r.json()
        items = self.extract(body)
        limit = int(config.get("batch_size", 25))
        return [self._stamp_watermark(self.to_signal(i), i)
                for i in items[:limit] if isinstance(i, dict)]


# ── Engineering & IT Ops ─────────────────────────────────────────────────────
# The largest slice of enterprise AI spend and, until now, the domain with no
# live integrations at all.
