"""
Billing provider bridge (theme M). One interface, two implementations:

* NoopBillingProvider — the default for every self-host install. Records nothing
  externally; usage rating still runs locally, it just is not pushed anywhere.
* StripeBillingProvider — managed cloud only. Pushes metered usage records +
  seat subscriptions to Stripe and verifies inbound webhook signatures.

The provider is selected by get_billing_provider(): Stripe only when
KAEOS_MANAGED_CLOUD is true, STRIPE_API_KEY is set, and the stripe SDK imports.
Otherwise the no-op keeps the platform fully functional with zero billing config.

The stripe SDK is synchronous; every call is offloaded with asyncio.to_thread so
the event loop is never blocked.
"""
import asyncio
import logging
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def _settings():
    from app.core.config import get_settings
    return get_settings()


class BillingProvider:
    """Interface. All methods are async and safe to await from request/job code."""

    enabled = False

    async def report_usage(
        self, db: AsyncSession, tenant_id: str, period: date, overage_units: int
    ) -> dict:
        raise NotImplementedError

    async def ensure_customer(self, db: AsyncSession, tenant_id: str) -> str | None:
        raise NotImplementedError

    def verify_webhook(self, payload: bytes, sig_header: str) -> dict:
        """Return the parsed, signature-verified Stripe event. Raises on a bad
        or missing signature — a webhook that cannot be verified is rejected."""
        raise NotImplementedError


class NoopBillingProvider(BillingProvider):
    enabled = False

    async def report_usage(self, db, tenant_id, period, overage_units) -> dict:
        return {"status": "noop", "usage_record_id": None}

    async def ensure_customer(self, db, tenant_id) -> str | None:
        return None

    def verify_webhook(self, payload: bytes, sig_header: str) -> dict:
        # Self-host has no Stripe secret; a webhook here is never legitimate.
        raise ValueError("Billing webhooks are disabled on this install")


class StripeBillingProvider(BillingProvider):
    enabled = True

    def __init__(self, stripe_mod, webhook_secret: str):
        self._stripe = stripe_mod
        self._webhook_secret = webhook_secret

    async def ensure_customer(self, db: AsyncSession, tenant_id: str) -> str | None:
        from app.models.billing import BillingAccount
        acct = await db.get(BillingAccount, tenant_id)
        if acct and acct.stripe_customer_id:
            return acct.stripe_customer_id
        cust = await asyncio.to_thread(
            self._stripe.Customer.create, metadata={"tenant_id": tenant_id}
        )
        if acct is None:
            acct = BillingAccount(tenant_id=tenant_id)
            db.add(acct)
        acct.stripe_customer_id = cust["id"]
        await db.commit()
        return cust["id"]

    async def report_usage(
        self, db: AsyncSession, tenant_id: str, period: date, overage_units: int
    ) -> dict:
        from app.models.billing import BillingAccount
        acct = await db.get(BillingAccount, tenant_id)
        if not acct or not acct.stripe_meter_item_id:
            # No metered subscription item wired for this tenant — nothing to push.
            return {"status": "noop", "usage_record_id": None}
        # action=set makes the push idempotent per (item, period): re-running a
        # period overwrites the quantity instead of accumulating it. The
        # idempotency key guards against a retried HTTP call within the tick.
        ts = int(datetime(period.year, period.month, period.day, tzinfo=timezone.utc).timestamp())
        rec = await asyncio.to_thread(
            lambda: self._stripe.SubscriptionItem.create_usage_record(
                acct.stripe_meter_item_id,
                quantity=int(overage_units),
                timestamp=ts,
                action="set",
                idempotency_key=f"usage:{tenant_id}:{period.isoformat()}",
            )
        )
        return {"status": "reported", "usage_record_id": rec.get("id")}

    def verify_webhook(self, payload: bytes, sig_header: str) -> dict:
        if not sig_header:
            raise ValueError("Missing Stripe-Signature header")
        # construct_event raises SignatureVerificationError on tamper/replay.
        return self._stripe.Webhook.construct_event(
            payload, sig_header, self._webhook_secret
        )


_provider: BillingProvider | None = None


def get_billing_provider() -> BillingProvider:
    """Cached provider selection. Stripe only when managed + configured."""
    global _provider
    if _provider is not None:
        return _provider
    s = _settings()
    api_key = getattr(s, "STRIPE_API_KEY", "") or ""
    webhook_secret = getattr(s, "STRIPE_WEBHOOK_SECRET", "") or ""
    if getattr(s, "KAEOS_MANAGED_CLOUD", False) and api_key:
        try:
            import stripe
            stripe.api_key = api_key
            _provider = StripeBillingProvider(stripe, webhook_secret)
            logger.info("[Billing] Stripe provider active")
        except Exception as e:
            logger.warning("[Billing] Stripe requested but unavailable (%s); using no-op", e)
            _provider = NoopBillingProvider()
    else:
        _provider = NoopBillingProvider()
    return _provider


def reset_billing_provider() -> None:
    """Test hook: clear the cached provider so settings changes take effect."""
    global _provider
    _provider = None


async def handle_webhook_event(db: AsyncSession, event: dict) -> dict:
    """Process a verified Stripe event idempotently. The event id is the
    idempotency key: a redelivered event is a no-op. We never trust a tenant id
    from the event body for authorization — customer metadata is used only to
    locate the local BillingAccount that WE created."""
    from app.models.billing import BillingAccount, StripeWebhookEvent

    event_id = event.get("id")
    event_type = event.get("type", "")
    if not event_id:
        return {"status": "ignored", "reason": "no event id"}

    seen = await db.get(StripeWebhookEvent, event_id)
    if seen and seen.processed:
        return {"status": "duplicate", "event_id": event_id}
    if seen is None:
        db.add(StripeWebhookEvent(event_id=event_id, event_type=event_type))

    obj = (event.get("data") or {}).get("object") or {}
    handled = False
    if event_type in ("customer.subscription.created", "customer.subscription.updated"):
        customer_id = obj.get("customer")
        acct = (await db.execute(
            select(BillingAccount).where(BillingAccount.stripe_customer_id == customer_id)
        )).scalar_one_or_none()
        if acct is not None:
            acct.stripe_subscription_id = obj.get("id")
            items = ((obj.get("items") or {}).get("data")) or []
            # First metered item becomes the usage-record target.
            for it in items:
                price = it.get("price") or {}
                if (price.get("recurring") or {}).get("usage_type") == "metered":
                    acct.stripe_meter_item_id = it.get("id")
                    break
            qty = sum(int(it.get("quantity") or 0) for it in items)
            if qty:
                acct.seats = qty
            handled = True

    mark = await db.get(StripeWebhookEvent, event_id)
    if mark is not None:
        mark.processed = True
    await db.commit()
    return {"status": "processed" if handled else "acknowledged", "event_id": event_id, "type": event_type}
