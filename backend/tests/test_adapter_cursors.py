"""M15: the incremental-pull cursor pattern is generalized across adapters.

Only ServiceNow advanced a delta cursor before; every other adapter re-read its
most-recent window each pass, so changes beyond batch_size were never paged past.
The base _RestAdapter now carries the pattern: updated_at_field surfaces the
source's own update time so the cursor advances, and cursor_params(config) turns
config['_cursor'] into an incremental filter. ServiceNow and Stripe do true
server-side incremental; GitHub/Zendesk are watermark-ready."""
from app.services.vendor_adapters.base import _RestAdapter
from app.services.vendor_adapters.devops import GitHubAdapter
from app.services.vendor_adapters.hr_finance import StripeAdapter
from app.services.vendor_adapters.itsm import ServiceNowAdapter, ZendeskAdapter


def test_base_default_is_a_fixed_window_no_cursor():
    assert _RestAdapter().cursor_params({"_cursor": "x"}) == {}


def test_stripe_does_true_incremental_and_surfaces_the_watermark():
    a = StripeAdapter()
    assert a.cursor_params({}) == {}
    assert a.cursor_params({"_cursor": 1_700_000_000}) == {"created[gte]": 1_700_000_000}
    # the created timestamp is surfaced as updated_at so the cursor advances
    item = {"id": "in_1", "created": 1_700_000_000, "total": 5000}
    sig = a._stamp_watermark(a.to_signal(item), item)
    assert sig["updated_at"] == 1_700_000_000


def test_servicenow_incremental_is_unchanged():
    q = ServiceNowAdapter().fetch_params({"_cursor": "2026-01-01 00:00:00"})
    assert "sys_updated_on>=2026-01-01 00:00:00" in q["sysparm_query"]


def test_github_and_zendesk_are_watermark_ready():
    gh, item = GitHubAdapter(), {"number": 7, "updated_at": "2026-08-01T00:00:00Z"}
    assert gh._stamp_watermark(gh.to_signal(item), item)["updated_at"] == "2026-08-01T00:00:00Z"
    # newest-updated-first so a fixed window still surfaces the freshest changes
    assert GitHubAdapter().fetch_params({})["sort"] == "updated"
    zd, t = ZendeskAdapter(), {"id": 9, "updated_at": "2026-08-02T00:00:00Z"}
    assert zd._stamp_watermark(zd.to_signal(t), t)["updated_at"] == "2026-08-02T00:00:00Z"


def test_watermark_is_a_noop_without_the_field():
    # An adapter that declares no updated_at_field must not invent an updated_at.
    a = _RestAdapter()
    assert "updated_at" not in a._stamp_watermark({"external_id": "1"}, {"modified": "x"})
