"""Result types shared by every deterministic compliance checker.

A checker is a pure function ``(context: dict) -> CheckResult``: no LLM, no DB,
no network - deterministic and unit-testable. It reads the structured facts it
needs from ``context`` and returns a verdict with citations. If the action
genuinely does not involve the regulated data, it returns NOT_APPLICABLE; if it
cannot verify because required inputs are absent, it returns ADVISORY (never a
silent PASS).
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Callable, List


class CheckStatus(str, enum.Enum):
    PASS = "PASS"                     # verified compliant
    BLOCK = "BLOCK"                   # deterministic violation - fail closed
    ADVISORY = "ADVISORY"            # concern / cannot fully verify (thin inputs)
    NOT_APPLICABLE = "NOT_APPLICABLE"  # the action does not touch this regime
    UNBACKED = "UNBACKED"            # no checker backs this tag - not verified


@dataclass
class Finding:
    code: str
    message: str
    severity: str = "HIGH"           # CRIT | HIGH | MEDI | LOW


@dataclass
class CheckResult:
    framework: str
    status: CheckStatus
    findings: List[Finding] = field(default_factory=list)
    citations: List[str] = field(default_factory=list)
    method: str = "deterministic"
    detail: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status in (CheckStatus.PASS, CheckStatus.NOT_APPLICABLE)

    @property
    def blocking(self) -> bool:
        """A BLOCK is a real violation; UNBACKED is an unverifiable claim. Both
        should stop a fail-closed gate - the point is that neither silently
        passes."""
        return self.status in (CheckStatus.BLOCK, CheckStatus.UNBACKED)

    def to_dict(self) -> dict:
        return {
            "framework": self.framework,
            "status": self.status.value,
            "passed": self.passed,
            "blocking": self.blocking,
            "method": self.method,
            "findings": [{"code": f.code, "message": f.message, "severity": f.severity}
                         for f in self.findings],
            "citations": self.citations,
            "detail": self.detail,
        }


# A checker: deterministic (context) -> CheckResult.
Checker = Callable[[dict], "CheckResult"]
