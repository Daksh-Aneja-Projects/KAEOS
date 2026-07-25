"""Real-data loaders — relational CRM + procurement (skipped when raw data absent).

The Kaggle CSVs/parquet are gitignored, so these tests skip in CI and run locally
where data/kaggle_raw/ is populated.
"""
import pytest

from benchmark.real_data import loaders


@pytest.mark.skipif(not loaders.sales_crm_available(), reason="sales parquet not present")
def test_sales_crm_is_relationally_consistent():
    crm = loaders.load_sales_crm(account_limit=100, activity_cap=2000)
    assert crm["accounts"], "expected accounts"
    account_ids = {a["account_id"] for a in crm["accounts"]}

    # Every child references an account in the returned set (no dangling refs).
    for c in crm["contacts"]:
        assert c["account_id"] in account_ids
    for o in crm["opportunities"]:
        assert o["account_id"] in account_ids
        assert o["stage"] in ("PROSPECTING", "QUALIFICATION", "PROPOSAL", "NEGOTIATION",
                              "CLOSED_WON", "CLOSED_LOST")
    for a in crm["activities"]:
        assert a["account_id"] in account_ids

    # Firmographics are parsed to real numbers.
    a0 = crm["accounts"][0]
    assert a0["employee_count"] > 0 and a0["arr"] > 0


@pytest.mark.skipif(not loaders.sales_crm_available(), reason="sales parquet not present")
def test_account_limit_bounds_the_result():
    small = loaders.load_sales_crm(account_limit=10)
    assert len(small["accounts"]) <= 10


def test_procurement_orders_shape():
    if not loaders.available().get("procurement_compliance"):
        pytest.skip("procurement CSV not present")
    rows = list(loaders.load_procurement_orders(limit=20))
    assert rows and all("po_id" in r and "supplier" in r for r in rows)
    r = rows[0]
    assert isinstance(r["quantity"], int)
    assert isinstance(r["compliant"], bool)
