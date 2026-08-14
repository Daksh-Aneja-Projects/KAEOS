"""Procurement department deterministic checkers: three-way match, segregation
of duties, spend authorization, OFAC sanctions. Pure functions - no LLM, no DB.
Mirrors tests/test_compliance_checkers.py."""
from app.compliance import CheckStatus, run_checks
from app.compliance.registry import list_frameworks


def _status(result, framework):
    return next(r["status"] for r in result["results"] if r["framework"] == framework)


def test_procurement_frameworks_are_registered():
    tags = {f["framework"] for f in list_frameworks()}
    assert {"THREE_WAY_MATCH", "SEGREGATION_OF_DUTIES",
            "SPEND_AUTHORIZATION", "OFAC_SANCTIONS"} <= tags


def test_three_way_match_qty_and_price():
    # Matched qty and price -> pass.
    ok = {"three_way_match": {"po": {"qty": 100, "unit_price": "9.50"},
                              "receipt": {"qty": 100},
                              "invoice": {"qty": 100, "unit_price": "9.50"}}}
    assert _status(run_checks(["THREE_WAY_MATCH"], ok), "THREE_WAY_MATCH") == CheckStatus.PASS.value

    # Invoice bills 120 but only 100 ordered/received -> block.
    qty_bad = {"three_way_match": {"po": {"qty": 100, "unit_price": "9.50"},
                                   "receipt": {"qty": 100},
                                   "invoice": {"qty": 120, "unit_price": "9.50"}}}
    assert _status(run_checks(["THREE_WAY_MATCH"], qty_bad), "THREE_WAY_MATCH") == CheckStatus.BLOCK.value

    # Invoice unit price higher than PO -> block.
    price_bad = {"three_way_match": {"po": {"qty": 100, "unit_price": "9.50"},
                                     "receipt": {"qty": 100},
                                     "invoice": {"qty": 100, "unit_price": "12.00"}}}
    assert _status(run_checks(["THREE_WAY_MATCH"], price_bad), "THREE_WAY_MATCH") == CheckStatus.BLOCK.value

    # A tolerance absorbs a small variance -> pass.
    within = {"three_way_match": {"po": {"qty": 100, "unit_price": "9.50"},
                                  "receipt": {"qty": 101},
                                  "invoice": {"qty": 100, "unit_price": "9.51"}},
              "qty_tolerance": 2, "price_tolerance": "0.05"}
    assert _status(run_checks(["THREE_WAY_MATCH"], within), "THREE_WAY_MATCH") == CheckStatus.PASS.value


def test_three_way_match_partial_delivery_and_over_receipt_pass():
    # Regression (finding 1): honest partial delivery invoiced at received amount
    # (PO=100, received=80, invoiced=80) must PASS, not false-block.
    partial = {"three_way_match": {"po": {"qty": 100, "unit_price": "9.50"},
                                   "receipt": {"qty": 80},
                                   "invoice": {"qty": 80, "unit_price": "9.50"}}}
    assert _status(run_checks(["THREE_WAY_MATCH"], partial), "THREE_WAY_MATCH") == CheckStatus.PASS.value

    # Over-receipt (PO=100, received=120, invoiced=100) must PASS; billing is
    # within both order and receipt.
    over_recv = {"three_way_match": {"po": {"qty": 100, "unit_price": "9.50"},
                                     "receipt": {"qty": 120},
                                     "invoice": {"qty": 100, "unit_price": "9.50"}}}
    assert _status(run_checks(["THREE_WAY_MATCH"], over_recv), "THREE_WAY_MATCH") == CheckStatus.PASS.value

    # Still blocks when invoice bills more than was received.
    over_bill = {"three_way_match": {"po": {"qty": 100, "unit_price": "9.50"},
                                     "receipt": {"qty": 80},
                                     "invoice": {"qty": 100, "unit_price": "9.50"}}}
    assert _status(run_checks(["THREE_WAY_MATCH"], over_bill), "THREE_WAY_MATCH") == CheckStatus.BLOCK.value


def test_three_way_match_price_discount_passes():
    # Regression (finding 2): vendor billing BELOW PO price is a discount -> PASS.
    discount = {"three_way_match": {"po": {"qty": 100, "unit_price": "9.50"},
                                    "receipt": {"qty": 100},
                                    "invoice": {"qty": 100, "unit_price": "7.00"}}}
    assert _status(run_checks(["THREE_WAY_MATCH"], discount), "THREE_WAY_MATCH") == CheckStatus.PASS.value


def test_three_way_match_not_applicable_and_advisory():
    # No match payload -> not applicable.
    assert _status(run_checks(["THREE_WAY_MATCH"], {}), "THREE_WAY_MATCH") == CheckStatus.NOT_APPLICABLE.value
    # Receipt missing entirely -> cannot verify -> advisory (never a silent pass).
    thin = {"three_way_match": {"po": {"qty": 100, "unit_price": "9.50"},
                                "invoice": {"qty": 100, "unit_price": "9.50"}}}
    assert _status(run_checks(["THREE_WAY_MATCH"], thin), "THREE_WAY_MATCH") == CheckStatus.ADVISORY.value


def test_segregation_of_duties():
    # Approver also received the goods -> conflict -> block.
    conflict = {"roles": {"requester": "alice@x", "approver": "bob@x", "receiver": "bob@x"}}
    assert _status(run_checks(["SEGREGATION_OF_DUTIES"], conflict), "SEGREGATION_OF_DUTIES") == CheckStatus.BLOCK.value

    # Three distinct identities -> pass (case/space insensitive).
    clean = {"roles": {"requester": "Alice@x", "approver": " bob@x ", "receiver": "carol@x"}}
    assert _status(run_checks(["SEGREGATION_OF_DUTIES"], clean), "SEGREGATION_OF_DUTIES") == CheckStatus.PASS.value

    # No roles at all -> not applicable.
    assert _status(run_checks(["SEGREGATION_OF_DUTIES"], {}), "SEGREGATION_OF_DUTIES") == CheckStatus.NOT_APPLICABLE.value
    # Only one role holder known -> cannot assess -> advisory.
    one = {"roles": {"approver": "bob@x"}}
    assert _status(run_checks(["SEGREGATION_OF_DUTIES"], one), "SEGREGATION_OF_DUTIES") == CheckStatus.ADVISORY.value


def test_spend_authorization_limit():
    # 25k invoice approved by someone capped at 10k -> block.
    over = {"authorization": {"amount": "25000", "approver_limit": "10000", "approver": "bob@x"}}
    assert _status(run_checks(["SPEND_AUTHORIZATION"], over), "SPEND_AUTHORIZATION") == CheckStatus.BLOCK.value

    # Within limit -> pass.
    ok = {"authorization": {"amount": "9000", "approver_limit": "10000"}}
    assert _status(run_checks(["SPEND_AUTHORIZATION"], ok), "SPEND_AUTHORIZATION") == CheckStatus.PASS.value

    # No amount -> not applicable; amount but no limit -> advisory.
    assert _status(run_checks(["SPEND_AUTHORIZATION"], {}), "SPEND_AUTHORIZATION") == CheckStatus.NOT_APPLICABLE.value
    no_limit = {"approval_amount": "9000"}
    assert _status(run_checks(["SPEND_AUTHORIZATION"], no_limit), "SPEND_AUTHORIZATION") == CheckStatus.ADVISORY.value


def test_ofac_sanctions_screening():
    denied = ["Blocked Trading LLC", {"name": "Sanctioned Corp", "id": "V-999"}]

    # Vendor on the list -> block.
    hit = {"vendor": {"name": "blocked trading llc"}, "sanctions_list": denied}
    assert _status(run_checks(["OFAC_SANCTIONS"], hit), "OFAC_SANCTIONS") == CheckStatus.BLOCK.value
    # Match by id -> block.
    hit_id = {"vendor": {"name": "Some Alias", "id": "V-999"}, "denied_parties": denied}
    assert _status(run_checks(["OFAC_SANCTIONS"], hit_id), "OFAC_SANCTIONS") == CheckStatus.BLOCK.value

    # Clean vendor -> pass.
    clean = {"vendor": {"name": "Acme Widgets Inc", "id": "V-001"}, "sanctions_list": denied}
    assert _status(run_checks(["OFAC_SANCTIONS"], clean), "OFAC_SANCTIONS") == CheckStatus.PASS.value

    # No vendor -> not applicable; vendor but no list -> advisory (never silent pass).
    assert _status(run_checks(["OFAC_SANCTIONS"], {}), "OFAC_SANCTIONS") == CheckStatus.NOT_APPLICABLE.value
    no_list = {"vendor": {"name": "Acme Widgets Inc"}}
    assert _status(run_checks(["OFAC_SANCTIONS"], no_list), "OFAC_SANCTIONS") == CheckStatus.ADVISORY.value


def test_ofac_sanctions_punctuation_near_match():
    # Regression (finding 3): 'Blocked Trading L.L.C.' must not slip past a list
    # entry 'Blocked Trading LLC' as a silent PASS; punctuation-only difference
    # is a near match -> ADVISORY.
    ctx = {"vendor": {"name": "Blocked Trading L.L.C."},
           "sanctions_list": ["Blocked Trading LLC"]}
    assert _status(run_checks(["OFAC_SANCTIONS"], ctx), "OFAC_SANCTIONS") == CheckStatus.ADVISORY.value
