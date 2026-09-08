"""Per-outcome-class Stripe pricing (F6): the metered unit is already the
verified outcome (usage_rating.py); this proves the per-class BREAKDOWN
that was already computed and then discarded at the reporting step now
actually reaches Stripe as separate prices - and, just as importantly,
that a tenant NOT on per-class pricing is completely unaffected."""
from datetime import date

from app.models.billing import BillingAccount
from app.services import stripe_bridge


# ── a minimal fake Stripe SDK - no network, no real credentials ─────────────

class _FakeUsageRecords:
    def __init__(self):
        self.calls: list[dict] = []

    def create_usage_record(self, item_id, quantity, timestamp, action, idempotency_key):
        self.calls.append({"item_id": item_id, "quantity": quantity, "action": action,
                           "idempotency_key": idempotency_key})
        return {"id": f"ur_{len(self.calls)}"}


class _FakePrices:
    def __init__(self, catalog: dict[str, str]):
        self.catalog = catalog

    def list(self, lookup_keys, active, limit):
        price_id = self.catalog.get(lookup_keys[0])
        return {"data": [{"id": price_id}] if price_id else []}


class _FakeCheckout:
    def __init__(self):
        self.calls: list[dict] = []

    class Session:
        pass

    def __getattr__(self, name):
        raise AttributeError(name)


def _fake_stripe(price_catalog: dict[str, str]):
    usage = _FakeUsageRecords()
    prices = _FakePrices(price_catalog)
    checkout_calls: list[dict] = []

    class _Session:
        @staticmethod
        def create(**kw):
            checkout_calls.append(kw)
            return {"url": "https://checkout.example/fake"}

    class _Checkout:
        Session = _Session

    class _Customer:
        @staticmethod
        def create(**kw):
            return {"id": "cus_fake"}

    mod = type("stripe", (), {
        "SubscriptionItem": usage, "Price": prices, "checkout": _Checkout,
        "Customer": _Customer,
    })
    mod._usage_calls = usage.calls
    mod._checkout_calls = checkout_calls
    return mod


# ── report_usage: per-class push, and the untouched flat fallback ───────────

async def test_flat_tenant_reporting_is_completely_unchanged(db):
    """No stripe_meter_items at all: report_usage must behave exactly as it
    did before this feature existed, even when a by_class breakdown is
    handed to it (a tenant not yet moved to per-class pricing)."""
    db.add(BillingAccount(tenant_id="t_flat", stripe_meter_item_id="si_flat"))
    await db.commit()
    fake = _fake_stripe({})
    provider = stripe_bridge.StripeBillingProvider(fake, "whsec_x")

    result = await provider.report_usage(db, "t_flat", date(2026, 9, 1), 42,
                                         by_class={"autonomous": 30, "assisted": 12})
    assert result["status"] == "reported"
    assert len(fake._usage_calls) == 1
    call = fake._usage_calls[0]
    assert call["item_id"] == "si_flat" and call["quantity"] == 42


async def test_per_class_tenant_reports_each_class_to_its_own_item(db):
    db.add(BillingAccount(tenant_id="t_class", stripe_meter_item_id="si_first",
                          stripe_meter_items={"autonomous": "si_auto", "assisted": "si_asst"}))
    await db.commit()
    fake = _fake_stripe({})
    provider = stripe_bridge.StripeBillingProvider(fake, "whsec_x")

    result = await provider.report_usage(db, "t_class", date(2026, 9, 1), 42,
                                         by_class={"autonomous": 30, "assisted": 12})
    assert result["status"] == "reported"
    by_item = {c["item_id"]: c["quantity"] for c in fake._usage_calls}
    assert by_item == {"si_auto": 30, "si_asst": 12}
    # Idempotent per (tenant, period, CLASS) - not one shared key that would
    # collide two different classes' pushes together.
    keys = {c["idempotency_key"] for c in fake._usage_calls}
    assert len(keys) == 2


async def test_per_class_tenant_with_no_by_class_falls_back_to_flat(db):
    """stripe_meter_items alone isn't enough - report_usage only reports
    per-class when a breakdown was actually computed this period."""
    db.add(BillingAccount(tenant_id="t_partial", stripe_meter_item_id="si_flat",
                          stripe_meter_items={"autonomous": "si_auto"}))
    await db.commit()
    fake = _fake_stripe({})
    provider = stripe_bridge.StripeBillingProvider(fake, "whsec_x")

    result = await provider.report_usage(db, "t_partial", date(2026, 9, 1), 10, by_class=None)
    assert result["status"] == "reported"
    assert fake._usage_calls[0]["item_id"] == "si_flat"


# ── checkout: per-class prices win when configured, else the flat one ───────

async def test_checkout_uses_per_class_prices_when_configured(db):
    fake = _fake_stripe({"team": "price_team", "team_metered_autonomous": "price_auto",
                        "team_metered_assisted": "price_asst"})
    provider = stripe_bridge.StripeBillingProvider(fake, "whsec_x")
    url = await provider.create_checkout_session(db, "t_new", "team",
                                                  "https://ok", "https://cancel")
    assert url == "https://checkout.example/fake"
    prices = {li["price"] for li in fake._checkout_calls[0]["line_items"]}
    assert prices == {"price_team", "price_auto", "price_asst"}


async def test_checkout_falls_back_to_flat_price_when_no_per_class_configured(db):
    fake = _fake_stripe({"team": "price_team", "team_metered": "price_team_flat"})
    provider = stripe_bridge.StripeBillingProvider(fake, "whsec_x")
    await provider.create_checkout_session(db, "t_new2", "team", "https://ok", "https://cancel")
    prices = {li["price"] for li in fake._checkout_calls[0]["line_items"]}
    assert prices == {"price_team", "price_team_flat"}


# ── usage_rating: the proportional allocation itself ─────────────────────────

async def test_by_class_overage_allocates_proportionally_to_volume(db, monkeypatch):
    from app.core import extensions as ext_mod
    from app.models.auth import Tenant
    from app.services import usage_rating

    db.add(Tenant(tenant_id="t_rate", name="Rate Co", plan="starter"))
    await db.commit()

    async def fake_classifier(db, tenant_id, start, end):
        # 90 autonomous, 30 assisted -> a 3:1 volume split.
        return {"metered_executions": 120, "by_class": {"autonomous": 90, "assisted": 30, "blocked": 5}}
    monkeypatch.setattr(ext_mod.extensions, "billing_classifier", fake_classifier)

    from app.core.entitlements import allowance_for_plan
    allowance = allowance_for_plan("starter")

    rating = await usage_rating.rate_tenant_period(db, "t_rate", date(2026, 9, 1))
    total_overage = rating["overage_units"]
    assert total_overage == max(0, 120 - allowance)
    if total_overage > 0:
        split = rating["by_class_overage"]
        assert split["autonomous"] + split["assisted"] in (total_overage, total_overage - 1, total_overage + 1)
        # 3:1 volume ratio should land the split close to 3:1 too (rounding
        # aside) - not an even/arbitrary split of the shared allowance pool.
        assert split["autonomous"] >= split["assisted"] * 2


async def test_by_class_overage_is_zero_when_within_allowance(db, monkeypatch):
    from app.core import extensions as ext_mod
    from app.models.auth import Tenant
    from app.services import usage_rating

    db.add(Tenant(tenant_id="t_rate2", name="Rate Co 2", plan="enterprise"))
    await db.commit()

    async def fake_classifier(db, tenant_id, start, end):
        return {"metered_executions": 5, "by_class": {"autonomous": 3, "assisted": 2, "blocked": 0}}
    monkeypatch.setattr(ext_mod.extensions, "billing_classifier", fake_classifier)

    rating = await usage_rating.rate_tenant_period(db, "t_rate2", date(2026, 9, 1))
    if rating["overage_units"] == 0:
        assert rating["by_class_overage"] == {"autonomous": 0, "assisted": 0}
