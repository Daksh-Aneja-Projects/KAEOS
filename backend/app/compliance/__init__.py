"""KAEOS compliance spine - deterministic statutory checkers, one governance
spine across every department (Department-as-a-Service).

The old path sent most compliance tags to an LLM to *guess* whether an action
was compliant, and an unbacked tag silently passed. This package replaces that
with deterministic, unit-testable checkers registered by framework tag, and a
registry that is HONEST about tags it cannot verify (UNBACKED, never a silent
pass). The LLM stays only as a labeled secondary screen for tags with no
deterministic checker.

Public surface::

    from app.compliance import run_checks, CheckStatus
    result = run_checks(["EEOC", "FLSA"], context)   # deterministic, no LLM
"""
from app.compliance.base import CheckResult, CheckStatus, Finding
from app.compliance.registry import (
    list_frameworks,
    register,
    run_checks,
)

__all__ = [
    "CheckResult", "CheckStatus", "Finding",
    "register", "run_checks", "list_frameworks",
]
