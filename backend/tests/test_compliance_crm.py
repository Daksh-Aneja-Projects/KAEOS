"""CRM / Sales department compliance checkers (GDPR, CCPA, TCPA, DSAR).
Deterministic pure functions - no LLM, no DB. Mirrors
tests/test_compliance_checkers.py."""
from app.compliance import CheckStatus, run_checks
from app.compliance.registry import list_frameworks


def _status(result, framework):
    return next(r["status"] for r in result["results"] if r["framework"] == framework)


def _codes(result, framework):
    r = next(r for r in result["results"] if r["framework"] == framework)
    return {f["code"] for f in r["findings"]}


def test_crm_frameworks_registered():
    tags = {f["framework"] for f in list_frameworks()}
    assert {"GDPR", "CCPA", "TCPA", "DSAR"} <= tags


def test_crm_frameworks_grouped_under_sales_department():
    """These checkers must self-register under the platform's canonical "sales"
    slug, not the legacy internal "crm" name - the Compliance Checker catalog
    page groups its left rail by department, and Department.slug is "sales"
    everywhere else in the product (routes, nav tab, seed data)."""
    depts = {f["framework"]: f["department"] for f in list_frameworks()
             if f["framework"] in ("GDPR", "CCPA", "TCPA", "DSAR")}
    assert depts == {"GDPR": "sales", "CCPA": "sales", "TCPA": "sales", "DSAR": "sales"}


# ---------------------------------------------------------------- GDPR Art 6
def test_gdpr_lawful_basis():
    # Valid non-consent basis -> pass.
    ok = {"processing": {"lawful_basis": "contract"}}
    assert _status(run_checks(["GDPR"], ok), "GDPR") == CheckStatus.PASS.value
    # Consent basis with affirmative consent -> pass.
    consent_ok = {"processing": {"lawful_basis": "consent", "consent": True}}
    assert _status(run_checks(["GDPR"], consent_ok), "GDPR") == CheckStatus.PASS.value
    # Consent basis without consent -> block.
    consent_no = {"processing": {"lawful_basis": "consent", "consent": False}}
    assert _status(run_checks(["GDPR"], consent_no), "GDPR") == CheckStatus.BLOCK.value
    # A basis outside Art 6 -> block.
    bogus = {"processing": {"lawful_basis": "because_we_want_to"}}
    assert _status(run_checks(["GDPR"], bogus), "GDPR") == CheckStatus.BLOCK.value
    # No processing described -> not applicable.
    assert _status(run_checks(["GDPR"], {}), "GDPR") == CheckStatus.NOT_APPLICABLE.value
    # Processing with no basis recorded -> advisory (never a silent pass).
    assert _status(run_checks(["GDPR"], {"processing": {}}),
                   "GDPR") == CheckStatus.ADVISORY.value


# ---------------------------------------------------------------- CCPA 1798.120
def test_ccpa_opt_out_of_sale():
    # Sale to a consumer who opted out -> block.
    opted = {"action": "sell_data", "data_subject": {"opted_out_of_sale": True}}
    assert _status(run_checks(["CCPA"], opted), "CCPA") == CheckStatus.BLOCK.value
    # Sale to a consumer who has not opted out -> pass.
    ok = {"action": "sell_data", "data_subject": {"opted_out_of_sale": False}}
    assert _status(run_checks(["CCPA"], ok), "CCPA") == CheckStatus.PASS.value
    # Not a sale/share action -> not applicable.
    assert _status(run_checks(["CCPA"], {"action": "email"}),
                   "CCPA") == CheckStatus.NOT_APPLICABLE.value
    # Sale but opt-out status unknown -> advisory.
    assert _status(run_checks(["CCPA"], {"action": "share"}),
                   "CCPA") == CheckStatus.ADVISORY.value


# ---------------------------------------------------------------- TCPA 47 USC 227
def test_tcpa_do_not_contact():
    # SMS to a number on the do-not-contact list -> block (tolerant of formatting).
    dnc = {"action": "sms", "phone": "(555) 123-4567",
           "do_not_contact": ["+15551234567"]}
    assert _status(run_checks(["TCPA"], dnc), "TCPA") == CheckStatus.BLOCK.value
    # Call to a consumer who opted out of contact -> block.
    opted = {"action": "call", "phone": "+15559999999",
             "data_subject": {"opted_out_of_contact": True}}
    assert _status(run_checks(["TCPA"], opted), "TCPA") == CheckStatus.BLOCK.value
    # Clean number, off the list, WITH prior express consent -> pass.
    ok = {"action": "sms", "phone": "+15550000000", "do_not_contact": ["+15551234567"],
          "data_subject": {"consent": True}}
    assert _status(run_checks(["TCPA"], ok), "TCPA") == CheckStatus.PASS.value
    # Not a call/SMS action -> not applicable.
    assert _status(run_checks(["TCPA"], {"action": "email"}),
                   "TCPA") == CheckStatus.NOT_APPLICABLE.value
    # Call with no target number -> advisory.
    assert _status(run_checks(["TCPA"], {"action": "call"}),
                   "TCPA") == CheckStatus.ADVISORY.value


def test_tcpa_no_dnc_list_is_advisory():
    # Finding 1: a clean number but NEITHER a do-not-contact list NOR any
    # opt-out/consent status verifies nothing -> advisory, not a silent pass.
    # (Manual "call" is a DNC-regime action, not a 227(b) consent action.)
    bare = {"action": "call", "phone": "+15550000000"}
    res = run_checks(["TCPA"], bare)
    assert _status(res, "TCPA") == CheckStatus.ADVISORY.value
    assert "no_dnc_list" in _codes(res, "TCPA")


def test_tcpa_autodial_without_consent_blocks():
    # Finding 2: 47 USC 227(b) - autodial/prerecorded/SMS with no prior express
    # consent is itself the violation, even with a clean, off-list number.
    no_consent = {"action": "autodial", "phone": "+15550000000",
                  "do_not_contact": []}
    res = run_checks(["TCPA"], no_consent)
    assert _status(res, "TCPA") == CheckStatus.BLOCK.value
    assert "no_prior_consent" in _codes(res, "TCPA")
    # Same autodial WITH consent -> the compliant case still passes.
    with_consent = {"action": "autodial", "phone": "+15550000000",
                    "do_not_contact": [], "data_subject": {"consent": True}}
    assert _status(run_checks(["TCPA"], with_consent), "TCPA") == CheckStatus.PASS.value


# ---------------------------------------------------------------- DSAR deadlines
def test_dsar_deadline():
    # GDPR request fulfilled 45 days after receipt (> 30) -> block.
    late = {"dsar": {"regime": "GDPR", "request_date": "2026-01-01",
                     "fulfilled_date": "2026-02-15"}}
    assert _status(run_checks(["DSAR"], late), "DSAR") == CheckStatus.BLOCK.value
    # GDPR request fulfilled within 30 days -> pass.
    ontime = {"dsar": {"regime": "GDPR", "request_date": "2026-01-01",
                       "fulfilled_date": "2026-01-20"}}
    assert _status(run_checks(["DSAR"], ontime), "DSAR") == CheckStatus.PASS.value
    # CCPA gets 45 days: 40 days is fine.
    ccpa_ok = {"dsar": {"regime": "CCPA", "request_date": "2026-01-01",
                        "fulfilled_date": "2026-02-10"}}
    assert _status(run_checks(["DSAR"], ccpa_ok), "DSAR") == CheckStatus.PASS.value
    # Still-open GDPR request, 40 days elapsed by the evaluation date -> block.
    open_late = {"dsar": {"regime": "GDPR", "request_date": "2026-01-01",
                          "status": "open", "as_of": "2026-02-10"}}
    assert _status(run_checks(["DSAR"], open_late), "DSAR") == CheckStatus.BLOCK.value
    # No DSAR in context -> not applicable.
    assert _status(run_checks(["DSAR"], {}), "DSAR") == CheckStatus.NOT_APPLICABLE.value
    # Open request with no evaluation date -> advisory (cannot measure).
    advis = {"dsar": {"regime": "CCPA", "request_date": "2026-01-01", "status": "open"}}
    assert _status(run_checks(["DSAR"], advis), "DSAR") == CheckStatus.ADVISORY.value


def test_dsar_gdpr_calendar_month_not_30_days():
    # Finding 3: GDPR Art 12(3) is one CALENDAR month, not a flat 30 days.
    # Jan 1 -> Feb 1 is 31 days; a flat-30 rule would falsely BLOCK this
    # fulfilment on the deadline day.
    on_month = {"dsar": {"regime": "GDPR", "request_date": "2026-01-01",
                         "fulfilled_date": "2026-02-01"}}
    assert _status(run_checks(["DSAR"], on_month), "DSAR") == CheckStatus.PASS.value
    # One day past the calendar month -> block.
    over = {"dsar": {"regime": "GDPR", "request_date": "2026-01-01",
                     "fulfilled_date": "2026-02-02"}}
    assert _status(run_checks(["DSAR"], over), "DSAR") == CheckStatus.BLOCK.value
    # End-of-month clamp: 31 Jan -> 28 Feb (no 31 Feb).
    clamp = {"dsar": {"regime": "GDPR", "request_date": "2026-01-31",
                      "fulfilled_date": "2026-02-28"}}
    assert _status(run_checks(["DSAR"], clamp), "DSAR") == CheckStatus.PASS.value


def test_dsar_reference_before_request_is_advisory():
    # Finding 3: a fulfilment/evaluation date preceding the request cannot be
    # measured -> advisory 'bad_dates', not a silent pass.
    backwards = {"dsar": {"regime": "GDPR", "request_date": "2026-01-01",
                          "fulfilled_date": "2025-12-15"}}
    res = run_checks(["DSAR"], backwards)
    assert _status(res, "DSAR") == CheckStatus.ADVISORY.value
    assert "bad_dates" in _codes(res, "DSAR")


def test_dsar_extension_extends_deadline():
    # Finding 3: a noticed extension pushes out the deadline.
    ext = {"dsar": {"regime": "GDPR", "request_date": "2026-01-01",
                    "fulfilled_date": "2026-02-20",
                    "extension_days": 60, "extension_noticed": True}}
    assert _status(run_checks(["DSAR"], ext), "DSAR") == CheckStatus.PASS.value
