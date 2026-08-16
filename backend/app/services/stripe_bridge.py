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

from sqlalchemy import select, update
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

    async def create_checkout_session(
        self, db: AsyncSession, tenant_id: str, plan: str,
        success_url: str, cancel_url: str,
    ) -> str | None:
        """Hosted checkout URL for a subscription to `plan`, or None if the
        provider cannot sell (self-host no-op)."""
        raise NotImplementedError

    async def create_portal_session(
        self, db: AsyncSession, tenant_id: str, return_url: str
    ) -> str | None:
        """Hosted billing-portal URL for the tenant's customer, or None."""
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

    async def create_checkout_session(self, db, tenant_id, plan, success_url, cancel_url) -> str | None:
        return None

    async def create_portal_session(self, db, tenant_id, return_url) -> str | None:
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

    async def _price_id_for(self, lookup_key: str, required: bool = True) -> str | None:
        """Resolve a Stripe price id by its lookup_key. The price->plan mapping
        lives on the Stripe object (lookup_key), the same convention
        _plan_from_items reads back off inbound subscription webhooks, so there
        is no second source of truth to drift."""
        prices = await asyncio.to_thread(
            lambda: self._stripe.Price.list(lookup_keys=[lookup_key], active=True, limit=1)
        )
        data = (prices.get("data") if isinstance(prices, dict) else prices.data) or []
        if not data:
            if required:
                raise ValueError(
                    f"No active Stripe price with lookup_key '{lookup_key}'. "
                    f"Create one in the Stripe dashboard with that lookup key."
                )
            return None
        return data[0]["id"]

    async def create_checkout_session(
        self, db: AsyncSession, tenant_id: str, plan: str,
        success_url: str, cancel_url: str,
    ) -> str | None:
        from app.models.billing import BillingAccount
        customer_id = await self.ensure_customer(db, tenant_id)
        acct = await db.get(BillingAccount, tenant_id)
        # One active subscription per tenant. A repeat checkout would create a
        # second, parallel subscription (double billing); send them to the portal
        # to change or cancel the existing one instead.
        if acct is not None and acct.stripe_subscription_id:
            raise ValueError(
                "This tenant already has an active subscription. "
                "Change or cancel it from the billing portal."
            )
        # Seat pricing: the base subscription bills for the tenant's purchased
        # seats, not a hardcoded 1.
        seats = max(1, int((acct.seats if acct is not None else 1) or 1))
        base_price = await self._price_id_for(plan)
        line_items = [{"price": base_price, "quantity": seats}]
        # Metered overage price (usage_type=metered) so the resulting subscription
        # carries a usage item that report_usage can push overage against. Without
        # it the subscription has no meter item and every overage push no-ops.
        # Optional: a plan may be billed flat with no metered overage.
        metered_price = await self._price_id_for(f"{plan}_metered", required=False)
        if metered_price:
            line_items.append({"price": metered_price})  # metered items take no quantity
        session = await asyncio.to_thread(
            lambda: self._stripe.checkout.Session.create(
                mode="subscription",
                customer=customer_id,
                line_items=line_items,
                success_url=success_url,
                cancel_url=cancel_url,
            )
        )
        return session.get("url")

    async def create_portal_session(
        self, db: AsyncSession, tenant_id: str, return_url: str
    ) -> str | None:
        customer_id = await self.ensure_customer(db, tenant_id)
        session = await asyncio.to_thread(
            lambda: self._stripe.billing_portal.Session.create(
                customer=customer_id, return_url=return_url
            )
        )
        return session.get("url")

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


def _plan_from_items(items: list) -> str | None:
    """Derive the KAEOS plan tier from a subscription's price line items.

    The tier is read from the price itself, in priority order:
    metadata.plan, then lookup_key, then nickname. This keeps the price->plan
    mapping on the Stripe object (where the operator configures the price)
    rather than in a second source of truth that can drift. Returns a valid
    tier slug, or None if none of the line items name a recognised tier.
    """
    from app.core.entitlements import PLAN_FEATURES
    for it in items:
        price = it.get("price") or {}
        for candidate in (
            (price.get("metadata") or {}).get("plan"),
            price.get("lookup_key"),
            price.get("nickname"),
        ):
            slug = (candidate or "").strip().lower()
            if slug in PLAN_FEATURES:
                return slug
    return None


# Stripe subscription statuses that DO / DO NOT entitle the paid tier.
_ACTIVE_STATUSES = frozenset({"active", "trialing"})
_REVOKE_STATUSES = frozenset({"canceled", "unpaid"})


def _plan_action(status: str | None, new_plan: str | None) -> tuple[str, str | None]:
    """Decide the entitlement move for a subscription upsert. Fail-closed: a tier
    is granted ONLY for a paying status (active/trialing); canceled/unpaid revoke
    to free; every other (transitional: incomplete/past_due/paused) status leaves
    the tier untouched so a grace period is neither granted fresh nor prematurely
    revoked. Returns (action, target_plan) where action is grant|revoke|none."""
    s = (status or "").strip().lower()
    if s in _REVOKE_STATUSES:
        return ("revoke", "free")
    if s in _ACTIVE_STATUSES and new_plan:
        return ("grant", new_plan)
    return ("none", None)


def _event_created(event: dict) -> int:
    try:
        return int(event.get("created") or 0)
    except (TypeError, ValueError):
        return 0


def _is_stale_event(acct, created: int) -> bool:
    """True when this event predates the last plan-affecting event we applied to
    the account, so an out-of-order redelivery cannot overwrite newer state (e.g.
    a late subscription.updated re-granting a tenant that was already canceled).
    Defensive: a no-op until billing_accounts.last_subscription_event_at exists."""
    last = int(getattr(acct, "last_subscription_event_at", 0) or 0)
    return bool(created and last and created < last)


def _advance_event_cursor(acct, created: int) -> None:
    if created and hasattr(acct, "last_subscription_event_at"):
        last = int(getattr(acct, "last_subscription_event_at", 0) or 0)
        acct.last_subscription_event_at = max(last, created)


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

    from app.models.auth import Tenant

    obj = (event.get("data") or {}).get("object") or {}
    _UPSERT = ("customer.subscription.created", "customer.subscription.updated")
    _CANCEL = ("customer.subscription.deleted",)
    _DUNNING = ("invoice.payment_failed",)
    _KNOWN = _UPSERT + _CANCEL + _DUNNING
    handled = False
    if event_type in _UPSERT:
        customer_id = obj.get("customer")
        acct = (await db.execute(
            select(BillingAccount).where(BillingAccount.stripe_customer_id == customer_id)
        )).scalar_one_or_none()
        if acct is not None:
            created = _event_created(event)
            if _is_stale_event(acct, created):
                # Superseded by a newer plan-affecting event we already applied;
                # acknowledge without mutating so a stale event cannot re-grant.
                handled = True
            else:
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
                # Sync the entitlement tier, but ONLY for a subscription that is
                # actually paying. Granting on any status would let an incomplete/
                # unpaid subscription unlock paid features and the higher allowance. The
                # plan tier is carried on the price (metadata.plan / lookup_key /
                # nickname) so no separate price->plan config drifts out of band.
                new_plan = _plan_from_items(items)
                action, target = _plan_action(obj.get("status"), new_plan)
                if action in ("grant", "revoke"):
                    await db.execute(
                        update(Tenant).where(Tenant.tenant_id == acct.tenant_id)
                        .values(plan=target)
                    )
                elif (obj.get("status") or "").strip().lower() in _ACTIVE_STATUSES:
                    # Paying, but the price names no recognised tier.
                    logger.warning(
                        "[Stripe] subscription %s for tenant %s carries no plan tier "
                        "on its price (set price metadata.plan or a lookup_key); "
                        "Tenant.plan left unchanged.", obj.get("id"), acct.tenant_id,
                    )
                _advance_event_cursor(acct, created)
                handled = True
    elif event_type in _DUNNING:
        # A failed payment does NOT change entitlements here: Stripe's own
        # dunning retries, and a terminal failure arrives later as
        # customer.subscription.deleted (handled below, drops the tenant to
        # free). This handler exists so the failure is VISIBLE the day it
        # happens - an audited event plus an operator notification - instead of
        # being silently discarded until the subscription dies weeks later.
        customer_id = obj.get("customer")
        acct = (await db.execute(
            select(BillingAccount).where(BillingAccount.stripe_customer_id == customer_id)
        )).scalar_one_or_none()
        if acct is not None:
            from app.core.audit import record_security_event
            from app.services.notifier import notify_fire_and_forget
            await record_security_event(
                tenant_id=acct.tenant_id, event_type="CONFIG_CHANGE",
                action="WRITE", result="ESCALATED", actor="stripe-webhook",
                resource_type="billing_account", resource_id=acct.tenant_id,
                details={"stripe_event": "invoice.payment_failed",
                         "invoice": obj.get("id")},
            )
            notify_fire_and_forget(
                acct.tenant_id, "billing.payment_failed",
                "Payment failed for your KAEOS subscription",
                "A subscription payment failed. The card will be retried "
                "automatically; if it keeps failing the plan drops to free. "
                "Update the payment method to keep paid features.",
            )
            handled = True
    elif event_type in _CANCEL:
        customer_id = obj.get("customer")
        acct = (await db.execute(
            select(BillingAccount).where(BillingAccount.stripe_customer_id == customer_id)
        )).scalar_one_or_none()
        if acct is not None:
            created = _event_created(event)
            if _is_stale_event(acct, created):
                handled = True
            else:
                # Subscription ended: drop the metered linkage and fall the tenant
                # back to free so cancelled tenants stop drawing paid entitlements
                # and the paid allowance.
                acct.stripe_subscription_id = None
                acct.stripe_meter_item_id = None
                await db.execute(
                    update(Tenant).where(Tenant.tenant_id == acct.tenant_id).values(plan="free")
                )
                _advance_event_cursor(acct, created)
                handled = True

    # A KNOWN event we could not complete (e.g. the local BillingAccount does not
    # exist yet - a create/webhook race) must NOT be marked processed, or the
    # linkage is lost forever (Stripe never redelivers a 200'd event). Leave it
    # unprocessed and signal a retry; unknown types are acknowledged (processed).
    # Dunning events for a customer we do not know are acknowledged, not
    # retried: there is no linkage to recover, unlike subscription events.
    recoverable_miss = (event_type in (_UPSERT + _CANCEL)) and not handled
    mark = await db.get(StripeWebhookEvent, event_id)
    if mark is not None and not recoverable_miss:
        mark.processed = True
    await db.commit()
    if recoverable_miss:
        return {"status": "retry", "event_id": event_id, "type": event_type}
    return {"status": "processed" if handled else "acknowledged", "event_id": event_id, "type": event_type}


if __name__ == "__main__":  # fail-closed status-gate self-check
    assert _plan_action("active", "team") == ("grant", "team")
    assert _plan_action("trialing", "business") == ("grant", "business")
    assert _plan_action("canceled", "team") == ("revoke", "free")
    assert _plan_action("unpaid", "team") == ("revoke", "free")
    assert _plan_action("past_due", "team") == ("none", None)   # grace: untouched
    assert _plan_action("incomplete", "team") == ("none", None)
    assert _plan_action("active", None) == ("none", None)       # no tier on price

    class _A:  # ordering guard
        last_subscription_event_at = 0
    a = _A()
    assert not _is_stale_event(a, 100)
    a.last_subscription_event_at = 200
    assert _is_stale_event(a, 100) and not _is_stale_event(a, 300)
    print("stripe_bridge self-check ok")
