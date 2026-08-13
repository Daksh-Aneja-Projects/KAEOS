"""Locks the model-probe reasoning grader (P0.5 fix, 2026-08-13).

The reasoning probe asks for the new TOTAL after a 20% discount on the largest of
three invoices (12,000 / 45,000 / 8,000): 45,000 -> 36,000, total = 56,000. The grader
must reward 56,000, not the 36,000 intermediate it used to reward, otherwise the
BYOK tier-ceiling (which caps every agent's autonomy) is computed from a broken signal.
"""
from app.services.model_probe import _grade_arithmetic


def test_rewards_requested_total():
    assert _grade_arithmetic("56000") == 1.0
    assert _grade_arithmetic("The new total is $56,000.") == 1.0
    assert _grade_arithmetic("45000 * 0.8 = 36000, so the total is 56000") == 1.0


def test_partial_for_discount_step_only():
    # 36,000 alone is the discounted invoice, NOT the requested total.
    assert _grade_arithmetic("36000") == 0.5


def test_zero_for_wrong_or_empty():
    assert _grade_arithmetic("no idea") == 0.0
    assert _grade_arithmetic("") == 0.0


if __name__ == "__main__":  # runnable without pytest
    test_rewards_requested_total()
    test_partial_for_discount_step_only()
    test_zero_for_wrong_or_empty()
    print("ok")
