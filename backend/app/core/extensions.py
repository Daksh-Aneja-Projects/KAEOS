"""
KAEOS Enterprise seam (fusion F0).

Open-core boundary: this module is the ONLY place the public core touches the
private ``kaeos_enterprise`` package. Core defines the hook points below; the
Enterprise package, when installed and enabled, registers implementations at
boot via :func:`load_enterprise`. Without it every slot stays empty and core
behaves exactly as before - the seam is inert.

The hook points (the public contract, kept stable for Enterprise releases):

- **gate-stage observers** - called on every gate transition of the 7-gate
  pipeline (``AgentExecutor._emit_gate``). Observers see, never decide: a hook
  exception is logged and swallowed, it can never alter a governed verdict.
- **pipeline-terminal observers** - called once per governed run with the
  final result dict (proof sealing registers here).
- **vendor adapter injection** - premium connectors pushed into the live pull
  catalog (``vendor_adapters.registry``), a push model so import order never
  matters.
- **billing outcome classifier** - a single slot consulted by usage rating
  when set (outcome-verified billing registers here; core never calls it
  until a classifier exists).
- **API routers** - Enterprise endpoints mounted under the API prefix at app
  build time.
- **periodic hooks** - named coroutines the core scheduler runs on a fixed
  cadence on the leader replica (the earned-autonomy ladder governor sweeps
  here). Tracked like every core job (GET /ops/scheduler); a failing hook
  is recorded, never fatal.

Entitlement gating for Enterprise ROUTES lives in
:func:`app.core.entitlements.require_enterprise`; this module only answers
"is the Enterprise package loaded and does it provide feature X".
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

__all__ = ["ExtensionRegistry", "extensions", "load_enterprise"]

GateStageHook = Callable[[dict, str, str, str], Awaitable[None]]
TerminalHook = Callable[[Dict[str, Any], dict, Dict[str, Any]], Awaitable[None]]


@dataclass
class ExtensionRegistry:
    """The slots Enterprise fills. One process-wide instance (``extensions``)."""

    gate_stage_hooks: List[GateStageHook] = field(default_factory=list)
    pipeline_terminal_hooks: List[TerminalHook] = field(default_factory=list)
    startup_hooks: List[Callable[[], Awaitable[None]]] = field(default_factory=list)
    billing_classifier: Optional[Callable[..., Any]] = None
    # The ONE slot that decides rather than observes: the debate gate's
    # arithmetic arbitrator. Called with the stored role dicts
    # ({proposer, advocate, arbitrator}) and the execution context; returns
    # None (the LLM arbitrator stands) or {"decision": PROCEED|ESCALATE|BLOCK,
    # "rationale": str, "proof_summary": dict}. Its decision space is exactly
    # the gate's own, and an erroring solver falls back to the LLM arbitrator
    # - it can widen scrutiny, never bypass the gate.
    debate_solver: Optional[Callable[[dict, dict], Awaitable[Optional[dict]]]] = None
    # Gate-3 confidence-cap providers (input trust lands here). Each is called
    # with (skill, context) and returns None or {"ceiling": float|None,
    # "force_hitl": bool, "reason": str}. Caps only ever LOWER effective
    # confidence or force human review - a provider can widen scrutiny, never
    # grant autonomy; an erroring provider fails closed to the failsafe
    # ceiling.
    confidence_caps: List[Callable[[dict, dict], Awaitable[Optional[dict]]]] = \
        field(default_factory=list)
    routers: List[Any] = field(default_factory=list)
    # (name, coroutine-function, interval hours) - registered into the core
    # scheduler at init_scheduler(); leader-guarded there like every core job.
    periodic_hooks: List[tuple] = field(default_factory=list)

    # Load state - surfaced honestly (ops console / status), never guessed.
    loaded: bool = False
    version: Optional[str] = None
    features: frozenset = frozenset()
    error: Optional[str] = None

    # ── registration API (what kaeos_enterprise.register() calls) ──────────

    def add_gate_stage_hook(self, hook: GateStageHook) -> None:
        self.gate_stage_hooks.append(hook)

    def add_pipeline_terminal_hook(self, hook: TerminalHook) -> None:
        self.pipeline_terminal_hooks.append(hook)

    def add_startup_hook(self, hook: Callable[[], Awaitable[None]]) -> None:
        """Async hook run once at boot, after the core's DB init (lifespan).
        Enterprise uses it to create/upgrade its own tables idempotently."""
        self.startup_hooks.append(hook)

    def set_billing_classifier(self, fn: Callable[..., Any]) -> None:
        self.billing_classifier = fn

    def set_debate_solver(self, fn: Callable[[dict, dict], Awaitable[Optional[dict]]]) -> None:
        self.debate_solver = fn

    def add_confidence_cap(self, fn: Callable[[dict, dict], Awaitable[Optional[dict]]]) -> None:
        self.confidence_caps.append(fn)

    def add_router(self, router: Any) -> None:
        self.routers.append(router)

    def add_periodic_hook(self, name: str, fn: Callable[[], Awaitable[None]],
                          *, hours: float) -> None:
        """Run ``fn`` every ``hours`` on the core scheduler (leader only)."""
        if not name or hours <= 0:
            raise ValueError("periodic hook needs a name and a positive interval")
        self.periodic_hooks.append((str(name), fn, float(hours)))

    def add_vendor_adapters(
        self, adapters: Dict[str, Any],
        required_config: Optional[Dict[str, list]] = None,
    ) -> None:
        """Push premium connectors into the live pull catalog.

        Mutates the shared registry dicts, so every existing reader (they all
        look up at call time) sees the additions regardless of import order.
        Never overwrites a core adapter: a name collision is a packaging bug
        and is refused loudly rather than silently shadowing core behavior.
        """
        from app.services.vendor_adapters import registry as _reg
        clash = set(adapters) & set(_reg.VENDOR_ADAPTERS)
        if clash:
            raise ValueError(
                f"Enterprise adapters may not shadow core adapters: {sorted(clash)}"
            )
        _reg.VENDOR_ADAPTERS.update(adapters)
        if required_config:
            _reg.VENDOR_REQUIRED_CONFIG.update(required_config)

    # ── queries ─────────────────────────────────────────────────────────────

    def provides(self, feature: Optional[str] = None) -> bool:
        return self.loaded and (feature is None or feature in self.features)

    def status(self) -> dict:
        """Honest load state for ops surfaces. Never fabricates a capability."""
        return {
            "installed": self.loaded or self.error is not None,
            "loaded": self.loaded,
            "version": self.version,
            "features": sorted(self.features),
            "error": self.error,
        }

    # ── dispatch (called from core hot paths; must never affect the run) ────

    async def dispatch_gate_stage(
        self, context: dict, gate: str, state: str, detail: str = "",
    ) -> None:
        for hook in self.gate_stage_hooks:
            try:
                await hook(context, gate, state, detail)
            except Exception:
                logger.error("[EE] gate-stage hook failed", exc_info=True)

    async def dispatch_pipeline_terminal(
        self, skill: Dict[str, Any], context: dict, result: Dict[str, Any],
    ) -> None:
        for hook in self.pipeline_terminal_hooks:
            try:
                await hook(skill, context, result)
            except Exception:
                logger.error("[EE] pipeline-terminal hook failed", exc_info=True)

    async def dispatch_startup(self) -> None:
        """Run Enterprise startup hooks (from the core lifespan, post-DB-init).

        A failing hook disables the WHOLE seam (reset to inert) rather than
        letting a half-initialised Enterprise run: its tables may be missing,
        so its request paths would 500 where the contract promises a
        professional refusal. Core boot continues as open core.
        """
        for hook in list(self.startup_hooks):
            try:
                await hook()
            except Exception as e:
                self.reset()
                self.error = f"startup: {type(e).__name__}: {e}"
                logger.error("[EE] Enterprise startup hook failed; seam reset "
                             "to inert: %s", self.error, exc_info=True)
                return

    def reset(self) -> None:
        """Return the seam to inert (used on failed registration and in tests)."""
        self.gate_stage_hooks.clear()
        self.pipeline_terminal_hooks.clear()
        self.startup_hooks.clear()
        self.billing_classifier = None
        self.debate_solver = None
        self.confidence_caps.clear()
        self.routers.clear()
        self.periodic_hooks.clear()
        self.loaded = False
        self.version = None
        self.features = frozenset()
        self.error = None


extensions = ExtensionRegistry()


def load_enterprise(app: Any = None, prefix: str = "") -> dict:
    """Import and register ``kaeos_enterprise`` if installed and enabled.

    Called once from ``main.py`` after core routes are mounted. Honest degrade
    on every path: not installed is a quiet no-op, ``KAEOS_EE_DISABLED=1``
    skips loading (used to keep the CI OpenAPI surface Enterprise-free), and a
    broken Enterprise package logs an error, resets the seam to inert, and
    lets core boot - Enterprise routes then refuse with the professional
    entitlement message instead of a stack trace.
    """
    if os.environ.get("KAEOS_EE_DISABLED", "").strip().lower() in {"1", "true", "yes"}:
        logger.info("[EE] KAEOS_EE_DISABLED set; Enterprise seam left inert")
        return extensions.status()
    try:
        import kaeos_enterprise  # type: ignore[import-not-found]
    except ImportError:
        logger.debug("[EE] kaeos_enterprise not installed; running open core")
        return extensions.status()
    try:
        kaeos_enterprise.register(extensions)
        extensions.loaded = True
        extensions.version = getattr(kaeos_enterprise, "__version__", None)
        extensions.features = frozenset(getattr(kaeos_enterprise, "FEATURES", ()))
        if app is not None:
            for router in extensions.routers:
                app.include_router(router, prefix=prefix)
        logger.info(
            "[EE] KAEOS Enterprise %s loaded (features: %s)",
            extensions.version, ", ".join(sorted(extensions.features)) or "none",
        )
    except Exception as e:
        # Fail to inert, never to half-loaded: a partially registered seam
        # would run some Enterprise hooks while its routes refuse.
        extensions.reset()
        extensions.error = f"{type(e).__name__}: {e}"
        logger.error("[EE] kaeos_enterprise failed to register; seam reset "
                     "to inert: %s", extensions.error, exc_info=True)
    return extensions.status()
