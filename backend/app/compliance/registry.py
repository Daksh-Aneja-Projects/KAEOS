"""Framework -> deterministic checker registry, fail-closed by construction.

Every checker module under ``app.compliance.checkers`` self-registers with the
``@register(...)`` decorator. ``run_checks`` looks up each requested framework
tag and runs its checker; a tag with NO backing checker returns UNBACKED (which
is ``blocking``) rather than silently passing - the exact hole in the old
LLM-guess path. Discovery is lazy and idempotent, so importing this module has
no import-time side effects on the checker packages.
"""
from __future__ import annotations

import importlib
import logging
import pkgutil
from dataclasses import dataclass
from threading import Lock
from typing import Dict, List, Optional

from app.compliance.base import CheckResult, CheckStatus, Checker, Finding

logger = logging.getLogger(__name__)


@dataclass
class CheckerEntry:
    framework: str
    department: str
    title: str
    citation: str
    fn: Checker


_REGISTRY: Dict[str, CheckerEntry] = {}
_DISCOVERED = False
_LOCK = Lock()


def register(framework: str, *, department: str, title: str, citation: str):
    """Decorator: bind a deterministic checker to a framework tag (upper-cased).
    Re-registering the same tag overwrites - last import wins, which keeps
    reloads sane in tests."""
    key = framework.strip().upper()

    def deco(fn: Checker) -> Checker:
        _REGISTRY[key] = CheckerEntry(key, department, title, citation, fn)
        return fn

    return deco


def _discover() -> None:
    global _DISCOVERED
    if _DISCOVERED:
        return
    with _LOCK:
        if _DISCOVERED:
            return
        from app.compliance import checkers as pkg
        for mod in pkgutil.iter_modules(pkg.__path__):
            if mod.name.startswith("_"):
                continue
            try:
                importlib.import_module(f"app.compliance.checkers.{mod.name}")
            except Exception:  # a broken checker module must not kill the app
                logger.exception("[compliance] failed to import checker module %s", mod.name)
        _DISCOVERED = True


def get(framework: str) -> Optional[CheckerEntry]:
    _discover()
    return _REGISTRY.get((framework or "").strip().upper())


def list_frameworks() -> List[dict]:
    """Every framework the platform can deterministically verify - the honest
    answer to 'which compliance claims are real vs a label'."""
    _discover()
    return sorted(
        ({"framework": e.framework, "department": e.department,
          "title": e.title, "citation": e.citation}
         for e in _REGISTRY.values()),
        key=lambda e: (e["department"], e["framework"]),
    )


def run_checks(frameworks: List[str], context: dict) -> dict:
    """Run every requested framework's deterministic checker against ``context``.

    Fail-closed: a tag with no backing checker returns UNBACKED (blocking), so
    an unbacked compliance claim can never read as satisfied. A checker that
    raises is treated as BLOCK (a broken control is not a passing control).
    """
    results: List[dict] = []
    for tag in dict.fromkeys(frameworks or []):  # de-dupe, keep order
        entry = get(tag)
        if entry is None:
            results.append(CheckResult(
                framework=(tag or "").strip().upper(),
                status=CheckStatus.UNBACKED,
                findings=[Finding("no_checker",
                                  f"No deterministic checker backs '{tag}'; "
                                  "this compliance claim is not verified.", "HIGH")],
                method="registry",
            ).to_dict())
            continue
        try:
            res = entry.fn(context or {})
            if not isinstance(res, CheckResult):
                raise TypeError(f"checker for {tag} returned {type(res).__name__}, not CheckResult")
            res.citations = res.citations or [entry.citation]
        except Exception as e:  # noqa: BLE001 - a broken control fails closed
            logger.exception("[compliance] checker %s raised", tag)
            res = CheckResult(
                framework=entry.framework, status=CheckStatus.BLOCK,
                findings=[Finding("checker_error", f"{entry.framework} checker failed: {e}", "HIGH")],
                citations=[entry.citation], method="deterministic",
            )
        results.append(res.to_dict())

    blocking = [r for r in results if r["blocking"]]
    advisory = [r for r in results if r["status"] == CheckStatus.ADVISORY.value]
    return {
        "verified": not blocking,
        "blocking": blocking,
        "advisory": advisory,
        "results": results,
    }
