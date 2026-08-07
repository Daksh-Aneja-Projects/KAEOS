"""
KAEOS L9 — LLM Router (KAEOS Data Fabric)

BYOK (Bring Your Own Key) provider-agnostic LLM gateway.
Uses LiteLLM for unified access to 100+ LLM providers.
Supports: OpenAI, Anthropic, Mistral, Groq, Ollama, Azure, Google, Cohere, and more.

Graceful degradation: when no LLM provider is available (no API keys configured
and no reachable Ollama server), the router returns deterministic SIMULATED
responses instead of raising. This keeps the dev stack fully runnable with no
external services. Simulated payloads are flagged with ``"simulated": True``.
"""
from typing import Optional
import logging
import time

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception
from circuitbreaker import circuit
from app.core.context import current_execution_id, current_skill_id, current_tenant_id

logger = logging.getLogger(__name__)

# Class-independent primitives live in sibling modules to keep this file focused
# on routing/completion. Re-exported here so existing imports such as
# `from app.services.llm_router import BudgetExceededError` keep working.
from app.services.llm_support import (  # noqa: F401  (re-exported for callers)
    _ollama_reachable,
    _embed_key,
    _embed_cache_get,
    _embed_cache_put,
    _EMBED_CACHE_STATS,
    embedding_dim,
    pseudo_embedding,
    BudgetExceededError,
    NoLLMProviderError,
    PIIScrubError,
)
from app.services.llm_simulation import simulated_completion


class LLMRouter:
    """
    Provider-agnostic LLM gateway — BYOK model.
    Organizations bring their own API keys and choose their models.
    """

    # Model tier routing — local-first with cloud fallback
    # Primary: Ollama local models for dev/testing
    # Fallback: Cloud models for production (when API keys are configured)
    # One resident 7b model for every text tier: qwen2.5-coder:7b fits a 6GB
    # GPU fully and is far stronger at strict-JSON/instruction-following than
    # phi4-mini (which probes 0 on instruction-following). Using the same
    # model across tiers also avoids Ollama swapping models between calls.
    # phi4-mini stays available as the BYOK weak-model demo.
    MODEL_TIERS = {
        "reasoning": "ollama/qwen2.5-coder:7b",           # Tier 1: debates, fairness, blueprints, agents
        "classification": "ollama/qwen2.5-coder:7b",      # Tier 2: intent classification, extraction, scoring
        "fast": "ollama/qwen2.5-coder:7b",                # Tier 3: formatting, simple ops
        # Tier 0 (nano): NON-reasoning, decorative/mechanical text only (e.g. a
        # plan narrative). A 1.5b coder model (~1.4GB VRAM) that can co-reside with
        # the resident 7b on a 6GB card WITHOUT evicting it — set
        # OLLAMA_MAX_LOADED_MODELS>=2 (+ a long OLLAMA_KEEP_ALIVE) so switching to
        # it never triggers a model swap. NEVER used for a governance decision.
        "nano": "ollama/qwen2.5-coder:1.5b",
        "embedding": "ollama/nomic-embed-text:latest",    # Tier E: embeddings for RAG
    }

    # Fallback chains — local first, cloud fallback when keys available
    FALLBACK_CHAINS = {
        "reasoning": ["ollama/qwen2.5-coder:7b", "claude-opus-4-8", "gpt-4o"],
        "classification": ["ollama/qwen2.5-coder:7b", "ollama/phi4-mini:latest", "gpt-4o-mini"],
        "fast": ["ollama/qwen2.5-coder:7b", "ollama/phi4-mini:latest", "gpt-4o-mini"],
        # nano falls back to the 7b (never worse quality), then a cheap cloud model.
        "nano": ["ollama/qwen2.5-coder:1.5b", "ollama/qwen2.5-coder:7b", "gpt-4o-mini"],
    }

    MAX_RETRIES = 3
    RETRY_BACKOFF_SECS = [1.0, 3.0, 8.0]  # Exponential-ish backoff

    # Maps a stored config layer onto an internal routing tier.
    LAYER_TO_TIER = {
        "TIER_1_COMPLEX": "reasoning",
        "TIER_2_STANDARD": "classification",
        "TIER_3_FAST": "fast",
        "TIER_EMBEDDING": "embedding",
    }

    def __init__(self, api_keys: Optional[dict] = None):
        self.api_keys = api_keys or {}
        self.embeddings_simulated: bool = False
        # The embedding model actually used by the most recent embed() call
        # (may differ from the requested model, e.g. rerouted to local nomic).
        # Stamped onto upserted vectors so a later pass can detect re-embedding.
        self.last_embedding_model: Optional[str] = None
        self._degraded: bool = False

    # ── BYOK: per-tenant model resolution ────────────────────────────────

    @classmethod
    async def for_tenant(cls, tenant_id: str) -> "LLMRouter":
        """
        Build a router bound to a tenant's own models and keys (BYOK).

        Tiers the tenant has not configured fall back to the platform defaults,
        so a partial configuration is always safe.
        """
        router = cls()
        # Bind the tenant up front so the router is tenant-scoped even if the
        # config load below fails (missing table, transient DB error) — it then
        # simply runs on the platform defaults rather than losing tenant identity.
        router.tenant_id = tenant_id
        try:
            from sqlalchemy import select
            from app.core.database import AsyncSessionLocal
            from app.models.settings import TenantLLMConfig
            from app.services.live_connectors import decrypt_secrets

            async with AsyncSessionLocal() as session:
                rows = (await session.execute(
                    select(TenantLLMConfig).where(TenantLLMConfig.tenant_id == tenant_id)
                )).scalars().all()

            tiers = dict(cls.MODEL_TIERS)
            chains = {k: list(v) for k, v in cls.FALLBACK_CHAINS.items()}
            keys: dict = {}
            profiles: dict = {}

            for row in rows:
                tier = cls.LAYER_TO_TIER.get(row.layer)
                if not tier:
                    continue
                tiers[tier] = row.model_name
                # The tenant's own model leads its fallback chain.
                chains[tier] = [row.model_name] + [
                    m for m in chains.get(tier, []) if m != row.model_name
                ]
                profiles[tier] = row.capability_profile or {}
                if row.api_key_encrypted:
                    try:
                        secret = decrypt_secrets(row.api_key_encrypted).get("api_key")
                        if secret:
                            keys[(row.provider or "").lower()] = secret
                    except ValueError:
                        logger.warning(
                            f"[LLM] tenant={tenant_id} layer={row.layer}: key undecryptable, skipping"
                        )
                if row.api_base:
                    keys["custom_base_url"] = row.api_base

            router.MODEL_TIERS = tiers
            router.FALLBACK_CHAINS = chains
            router.api_keys = keys
            router.tenant_profiles = profiles
        except Exception as e:
            logger.warning(f"[LLM] tenant config load failed for {tenant_id}: {e} — using defaults")
        return router

    def confidence_ceiling(self, model_tier: str = "reasoning") -> float:
        """
        The maximum confidence any decision may claim on this tenant's model.

        Derived from the probe's tier_ceiling: an unprobed or fully capable
        model imposes no cap (1.0); a weak model caps confidence, which pushes
        decisions below the HITL threshold and into human review automatically.
        """
        profile = getattr(self, "tenant_profiles", {}).get(model_tier) or {}
        ceiling = profile.get("tier_ceiling")
        if ceiling is None:
            return 1.0
        # Never cap below 0.5 — the gates, not the cap, decide what is unusable.
        return max(0.5, min(1.0, float(ceiling)))

    # ── Data-residency helpers (GDPR/DPDP) ───────────────────────────────

    # Every credential/model that would send prompt text off-box. When data
    # residency is local/eu/in/on_prem, none of these may be used — PII must
    # never leave the region, so only ``ollama/...`` (local) routing is allowed.
    _CLOUD_KEY_NAMES = (
        "openai", "anthropic", "groq", "mistral", "cohere", "custom_base_url",
    )

    @staticmethod
    def _is_local_model(model: str) -> bool:
        """Only Ollama runs in-region; everything else is cloud egress."""
        return bool(model) and model.startswith("ollama/")

    @staticmethod
    def _local_llm_only() -> bool:
        """True when DATA_RESIDENCY pins inference on-region (local/eu/in/on_prem)."""
        try:
            from app.core.config import get_settings
            return bool(get_settings().local_llm_only)
        except Exception:
            # Settings unavailable -> assume inference is not region-pinned.
            return False

    # ── Provider availability detection ──────────────────────────────────

    def _effective_keys(self, tenant_api_keys: Optional[dict] = None) -> dict:
        """Merge instance keys, tenant keys, and configured settings keys.

        DATA RESIDENCY: when local_llm_only is set, cloud credentials are
        stripped entirely so nothing downstream (provider_available / _call_llm)
        can accidentally route PII to a cloud provider. Only the Ollama base URL
        survives, keeping all inference in-region.
        """
        keys = dict(self.api_keys)
        try:
            from app.core.config import get_settings
            settings = get_settings()
            if settings.OPENAI_API_KEY:
                keys.setdefault("openai", settings.OPENAI_API_KEY)
            if settings.ANTHROPIC_API_KEY:
                keys.setdefault("anthropic", settings.ANTHROPIC_API_KEY)
            if settings.GROQ_API_KEY:
                keys.setdefault("groq", settings.GROQ_API_KEY)
        except Exception:
            # Platform-wide fallback keys are optional. Without them the tenant
            # keys below still apply, and a call with no usable key fails at the
            # provider with a clear error rather than being silently skipped.
            pass
        if tenant_api_keys:
            keys.update(tenant_api_keys)
        if self._local_llm_only():
            # Drop every cloud credential/endpoint — local-only means local-only.
            for k in self._CLOUD_KEY_NAMES:
                keys.pop(k, None)
        return keys

    async def provider_available(self, tenant_api_keys: Optional[dict] = None) -> bool:
        """True if any real LLM provider is available (cloud key or reachable Ollama).

        Under local_llm_only, _effective_keys has already stripped all cloud
        credentials, so this collapses to "is a local Ollama reachable?" — if not,
        the caller fails closed (NoLLMProviderError) rather than reaching cloud.
        """
        keys = self._effective_keys(tenant_api_keys)
        cloud_providers = ("openai", "anthropic", "groq", "mistral", "cohere")
        if any(keys.get(p) for p in cloud_providers):
            return True
        if keys.get("custom_base_url"):
            return True
        base_url = keys.get("ollama_base_url", "http://localhost:11434")
        return await _ollama_reachable(base_url)

    @staticmethod
    def is_retryable_error(exception: BaseException) -> bool:
        try:
            import litellm
            if isinstance(exception, (
                litellm.RateLimitError,
                litellm.InternalServerError,
                litellm.ServiceUnavailableError,
                litellm.APIConnectionError,
            )):
                return True
        except ImportError:
            # litellm not installed: fall through to the string matching below,
            # which classifies retryable errors without the typed exceptions.
            pass
        err_str = str(exception).lower()
        return "429" in err_str or "rate" in err_str or "503" in err_str or "500" in err_str or "timeout" in err_str

    @circuit(failure_threshold=5, recovery_timeout=60)
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception(is_retryable_error)
    )
    async def _call_model_with_retry(
        self, chain_model: str, prompt: str, system_prompt: Optional[str],
        temperature: float, max_tokens: int, tenant_api_keys: Optional[dict]
    ) -> dict:
        return await self._call_llm(
            chain_model, prompt, system_prompt, temperature,
            max_tokens, tenant_api_keys
        )

    async def complete(
        self,
        prompt: str,
        model: str = "gpt-4o-mini",
        model_tier: Optional[str] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        tenant_api_keys: Optional[dict] = None,
    ) -> dict | str:
        """
        Send a completion request through LiteLLM with retry + fallback.
        
        If model_tier is provided, it maps to a configured model and returns
        the content string directly (convenience for AEOS services).
        Otherwise returns: {"content": str, "model": str, "usage": {...}}
        """
        # CI lane: KAEOS_FAKE_LLM=1 returns a deterministic JSON superset so
        # the gate/pipeline logic is testable without any model. Never set in
        # a real deployment - responses carry an explicit fake marker.
        import os
        if os.environ.get("KAEOS_FAKE_LLM", "").lower() in ("1", "true"):
            fake = (
                '{"status": "SUCCESS", "decision": "deterministic fake-llm response", '
                '"confidence": 0.9, "violations": [], "verdict": "PROCEED", '
                '"severity": "MEDIUM", "category": "general", "score": 0.8, '
                '"fake_llm": true}'
            )
            if model_tier:
                return fake
            return {"content": fake, "model": "fake-llm", "usage": {}}

        # Budget gate BEFORE tier resolution: _record_cost meters after the fact,
        # but a tenant whose hard limit resolves to BLOCK must not reach a paid
        # model, and a DEGRADE verdict must down-tier THIS call — not the next
        # one — so it has to run before the tier is chosen.
        await self._check_budget_gate(prompt)

        # Resolve model from tier if provided
        return_string = False
        fallback_chain = [model]
        if model_tier:
            if model_tier not in self.MODEL_TIERS:
                raise ValueError(
                    f"Unknown model_tier {model_tier!r}; expected one of "
                    f"{sorted(self.MODEL_TIERS)}"
                )
            effective_tier = model_tier
            if self._degraded and model_tier in ("reasoning", "classification"):
                effective_tier = "fast"
            model = self.MODEL_TIERS[effective_tier]
            fallback_chain = self.FALLBACK_CHAINS.get(effective_tier, [model])
            return_string = True

        # DATA RESIDENCY: when local-only, strip every cloud model out of the
        # routing chain so PII can only ever reach a local Ollama model. If the
        # requested chain was entirely cloud, substitute the local tier default
        # rather than reaching cloud; if no Ollama is up, _call_llm fails closed
        # with NoLLMProviderError instead of silently falling back to cloud.
        if self._local_llm_only():
            local_chain = [m for m in fallback_chain if self._is_local_model(m)]
            if not local_chain:
                local_defaults = [
                    m for m in self.MODEL_TIERS.values() if self._is_local_model(m)
                ]
                local_chain = local_defaults[:1] or ["ollama/qwen2.5-coder:7b"]
                logger.info(
                    "[LLM] local_llm_only: requested chain was cloud-only; "
                    "routing to local default %s to keep PII in-region", local_chain[0]
                )
            fallback_chain = local_chain

        last_error = None
        for chain_model in fallback_chain:
            try:
                _t0 = time.perf_counter()
                result = await self._call_model_with_retry(
                    chain_model, prompt, system_prompt, temperature,
                    max_tokens, tenant_api_keys
                )
                # Meter the call. /billing claimed its numbers came from "CostEvent
                # rows written by the LLM router" - the router had no cost code at
                # all, so every figure it reported came from seeded rows. Now the
                # calls actually record themselves.
                await self._record_cost(
                    model=result.get("model") or chain_model,
                    model_tier=model_tier or "unspecified",
                    usage=result.get("usage") or {},
                    latency_ms=int((time.perf_counter() - _t0) * 1000),
                )
                if return_string:
                    return result["content"]
                return result
            except ImportError:
                logger.warning("LiteLLM not installed — LLM routing unavailable")
                return "" if return_string else {"content": "", "model": model, "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}
            except Exception as e:
                last_error = e
                logger.error(f"[LLM] {chain_model} failed after retries/circuit breaker: {e}")

        logger.error(f"[LLM] All fallback models exhausted. Last error: {last_error}")
        raise last_error or RuntimeError("All LLM fallback models failed")

    async def stream_complete(
        self,
        prompt: str,
        model: str = "gpt-4o-mini",
        model_tier: Optional[str] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        tenant_api_keys: Optional[dict] = None,
    ):
        """Stream content deltas, with the same governance as ``complete()``.

        Deliberately mirrors ``complete()``'s orchestration rather than calling
        past it: the budget gate still runs before a model is chosen, the
        degraded tier still applies, the data-residency filter still strips
        cloud models, and the call is still metered into CostEvent. A streaming
        path that skipped any of those would be a hole in the governance the
        product sells.

        Fallback differs, and it has to: once a delta has been handed to the
        caller it is already on the client's screen, so a mid-stream failure
        cannot be retried on the next model without duplicating text. We fall
        back only while nothing has been emitted yet, and propagate after that.
        """
        import os
        if os.environ.get("KAEOS_FAKE_LLM", "").lower() in ("1", "true"):
            yield (
                '{"status": "SUCCESS", "decision": "deterministic fake-llm response", '
                '"confidence": 0.9, "violations": [], "verdict": "PROCEED", '
                '"severity": "MEDIUM", "category": "general", "score": 0.8, '
                '"fake_llm": true}'
            )
            return

        await self._check_budget_gate(prompt)

        fallback_chain = [model]
        if model_tier:
            if model_tier not in self.MODEL_TIERS:
                raise ValueError(
                    f"Unknown model_tier {model_tier!r}; expected one of "
                    f"{sorted(self.MODEL_TIERS)}"
                )
            effective_tier = model_tier
            if self._degraded and model_tier in ("reasoning", "classification"):
                effective_tier = "fast"
            fallback_chain = self.FALLBACK_CHAINS.get(
                effective_tier, [self.MODEL_TIERS[effective_tier]]
            )

        if self._local_llm_only():
            local_chain = [m for m in fallback_chain if self._is_local_model(m)]
            if not local_chain:
                local_defaults = [m for m in self.MODEL_TIERS.values() if self._is_local_model(m)]
                local_chain = local_defaults[:1] or ["ollama/qwen2.5-coder:7b"]
            fallback_chain = local_chain

        last_error = None
        for chain_model in fallback_chain:
            emitted = False
            usage: dict = {}
            _t0 = time.perf_counter()
            try:
                async for delta in self._stream_llm(
                    chain_model, prompt, system_prompt, temperature,
                    max_tokens, tenant_api_keys, usage,
                ):
                    emitted = True
                    yield delta
                await self._record_cost(
                    model=usage.get("model") or chain_model,
                    model_tier=model_tier or "unspecified",
                    usage=usage,
                    latency_ms=int((time.perf_counter() - _t0) * 1000),
                )
                return
            except Exception as e:
                last_error = e
                logger.error(f"[LLM] streaming {chain_model} failed: {e}")
                if emitted:
                    # Partial output is already on the client; a retry would
                    # append a second answer to the first.
                    raise
        raise last_error or RuntimeError("All LLM fallback models failed")

    async def _check_budget_gate(self, prompt: str) -> None:
        """Refuse dispatch when the tenant's budget enforcement resolves to BLOCK.

        Fails open on infrastructure errors (a broken budget check must not take
        down inference), but a BLOCK verdict is a hard stop.
        """
        verdict = None
        try:
            tenant_id = current_tenant_id.get()
            if not tenant_id:
                return  # not in a tenant context (probe/boot) - nothing to enforce
            from app.core.database import AsyncSessionLocal
            from app.services.cost_governor import CostGovernorService
            async with AsyncSessionLocal() as db:
                verdict = await CostGovernorService.check_budget(
                    db, tenant_id, estimated_tokens=max(1, len(prompt) // 4)
                )
        except Exception as e:
            logger.warning(f"[LLM] budget check failed open: {e}")
            return
        if verdict:
            action = verdict.get("action")
            if action == "BLOCK":
                raise BudgetExceededError(
                    f"LLM budget exhausted for this tenant "
                    f"({verdict.get('usage_pct', '?')}% of hard limit used) - "
                    f"raise the budget or wait for the period to reset"
                )
            if action == "DEGRADE":
                logger.warning(
                    f"[LLM] Budget DEGRADE triggered ({verdict.get('usage_pct', '?')}% used) "
                    f"— forcing model tier down to 'fast'"
                )
                self._degraded = True

    async def _record_cost(self, model: str, model_tier: str, usage: dict, latency_ms: int) -> None:
        """Write one CostEvent per real model call. Never raises."""
        try:
            tenant_id = current_tenant_id.get()
            if not tenant_id:
                return  # not in a tenant context (probe/boot) - nothing to bill
            inp = int(usage.get("prompt_tokens") or 0)
            out = int(usage.get("completion_tokens") or 0)
            if not (inp or out):
                return

            # Local models cost nothing; that is a real $0, not a missing number.
            cost = 0.0
            try:
                import litellm
                prompt_cost, completion_cost = litellm.cost_per_token(
                    model=model, prompt_tokens=inp, completion_tokens=out
                )
                cost = float(prompt_cost + completion_cost)
            except Exception:
                # litellm has no price table for this model -> report 0 rather
                # than fail the completion over a bookkeeping gap.
                cost = 0.0

            from app.core.database import AsyncSessionLocal
            from app.services.cost_governor import CostGovernorService
            # No explicit tenant binding here: the `after_begin` listener in
            # app/core/database.py binds every transaction from the contextvar.
            async with AsyncSessionLocal() as db:
                await CostGovernorService.record_usage(
                    db=db, tenant_id=tenant_id, model_name=model, model_tier=model_tier,
                    input_tokens=inp, output_tokens=out, cost_usd=cost,
                    latency_ms=latency_ms,
                    skill_id=current_skill_id.get(),
                    execution_id=current_execution_id.get(),
                    request_type=model_tier,
                )
                await db.commit()
        except Exception as e:
            # WARNING, not debug: metering silently returning nothing is how
            # /billing ended up reporting seeded fiction in the first place.
            # An ImportError in here hid behind a debug line for an entire
            # round of "verified" work. If cost stops being recorded, say so.
            logger.warning(f"[LLM] cost metering FAILED (usage not recorded): {e}")

    async def complete_json(self, *args, **kwargs) -> dict:
        """Call complete() and robustly extract/parse JSON from the response."""
        from app.services.json_utils import extract_json_object

        res = await self.complete(*args, **kwargs)
        content = res if isinstance(res, str) else res.get("content", "{}")
        try:
            return extract_json_object(content)
        except ValueError as e:
            logger.error(f"Failed to parse JSON from LLM output: {str(content)[:300]}")
            raise ValueError("Could not extract JSON from LLM response") from e

    async def _scrub_for_cloud(self, text: Optional[str]) -> Optional[str]:
        """Redact PII from text before it leaves for a cloud provider.

        Belt-and-suspenders, because neither layer alone is sufficient:
          1. Presidio NER (via the shared scrubber) catches names and contextual
             PII — but at a useful precision threshold it can MISS a bare phone
             number or SSN, so it cannot be the only line of defence.
          2. ``redact_structured_pii`` then deterministically removes structured
             direct identifiers (email/phone/SSN/credit-card/IP/IBAN) regardless
             of NER confidence. This runs even when Presidio is absent.

        A lower Presidio threshold (0.4) is deliberate here: over-redacting a
        borderline token before it leaves the region is the safe error. Any
        failure returns the best text we have — scrubbing must never take down
        inference. Only CLOUD calls reach this path; local Ollama skips it.
        """
        if not text:
            return text
        scrubbed = text
        try:
            from app.transforms.pii_scrubber import PIIScrubberNode
            from app.transforms.base import TransformRecord

            node = PIIScrubberNode(
                "llm_cloud_egress_scrub",
                {"action": "redact", "confidence_threshold": 0.4},
            )
            record = TransformRecord(
                id="llm_egress", source_record_id="llm_egress",
                data={}, text_content=text,
            )
            result = await node.process([record])
            if result.records and result.records[0].text_content is not None:
                scrubbed = result.records[0].text_content
        except Exception as e:
            logger.warning(f"[LLM] Presidio egress scrub failed, applying structured backstop only: {e}")

        # Deterministic structured backstop — always runs, even if Presidio threw
        # or is not installed. This is what guarantees a phone/SSN never egresses.
        try:
            from app.transforms.pii_scrubber import redact_structured_pii
            scrubbed, _ = redact_structured_pii(scrubbed)
        except Exception as e:
            from app.core.config import get_settings
            if get_settings().pii_egress_fail_closed:
                # Under a data-residency policy we cannot guarantee direct
                # identifiers were removed — block the cloud call rather than leak.
                raise PIIScrubError(
                    f"structured PII backstop failed under data-residency policy: {e}"
                ) from e
            logger.warning(f"[LLM] structured PII backstop failed, proceeding: {e}")
        return scrubbed

    async def _call_llm(
        self, model: str, prompt: str, system_prompt: Optional[str],
        temperature: float, max_tokens: int, tenant_api_keys: Optional[dict],
    ) -> dict:
        """Single LLM call — extracted for retry/fallback orchestration.

        If no provider is available, returns a deterministic SIMULATED response
        ONLY when simulation is explicitly permitted (DEV_MODE / ALLOW_SIMULATED_LLM).
        Otherwise it FAILS CLOSED by raising NoLLMProviderError, so a headless
        deployment cannot silently auto-approve governance gates on fake output.
        """
        if not await self.provider_available(tenant_api_keys):
            from app.core.config import get_settings
            if not get_settings().simulated_llm_allowed:
                raise NoLLMProviderError(
                    "No LLM provider is reachable (no cloud key, no local Ollama) "
                    "and ALLOW_SIMULATED_LLM is off. Refusing to fabricate a "
                    "governance decision. Configure a provider or set "
                    "ALLOW_SIMULATED_LLM=true for offline local testing only."
                )
            return self._simulated_completion(prompt, system_prompt)

        messages, model, api_base, api_key, is_local = await self._prepare_call(
            model, prompt, system_prompt, tenant_api_keys
        )

        import litellm
        from app.core.config import get_settings as _get_cfg
        _cfg = _get_cfg()
        response = await litellm.acompletion(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            api_base=api_base,
            api_key=api_key,
            timeout=_cfg.LLM_LOCAL_TIMEOUT_SECONDS if is_local else _cfg.LLM_TIMEOUT_SECONDS,
        )

        return {
            "content": response.choices[0].message.content,
            "model": response.model,
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                "total_tokens": response.usage.total_tokens if response.usage else 0,
            },
        }

    async def _prepare_call(
        self, model: str, prompt: str, system_prompt: Optional[str],
        tenant_api_keys: Optional[dict],
    ) -> tuple:
        """Everything a provider call needs, done once for blocking AND streaming.

        Shared deliberately: the PII scrub and the data-residency rules below are
        security controls, and two copies of them would eventually disagree. The
        streaming path must be exactly as safe as the blocking one.

        Returns ``(messages, model, api_base, api_key, is_local)``.
        """
        effective_keys = {**self.api_keys, **(tenant_api_keys or {})}

        # PII SCRUB BEFORE CLOUD EGRESS: local Ollama runs in-region and needs
        # no scrub (avoid the overhead), but any cloud call may exfiltrate PII.
        # Scrub the prompt/system prompt through Presidio when SCRUB_PII_BEFORE_LLM
        # is set, or whenever we are NOT pinned local-only (defence in depth).
        # A scrub failure must never break inference — it degrades to unscrubbed.
        if not self._is_local_model(model):
            from app.core.config import get_settings
            _s = get_settings()
            if _s.SCRUB_PII_BEFORE_LLM or not _s.local_llm_only:
                try:
                    prompt = await self._scrub_for_cloud(prompt)
                    system_prompt = await self._scrub_for_cloud(system_prompt)
                except PIIScrubError:
                    # Fail closed: never send unscrubbed PII to a cloud provider
                    # under a data-residency policy. Propagate to block the call.
                    raise
                except Exception as e:
                    if _s.pii_egress_fail_closed:
                        raise PIIScrubError(
                            f"PII scrub failed under data-residency policy; "
                            f"blocking cloud egress: {e}"
                        ) from e
                    logger.warning(f"[LLM] pre-cloud PII scrub skipped (non-fatal): {e}")

        # NEVER set litellm module globals — they are shared across all
        # concurrent coroutines and cause cross-tenant credential leaks under
        # BYOK. The per-call `api_key` param on acompletion() is the safe path.

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        api_base = None
        is_local = model.startswith(("ollama/", "custom/"))
        if model.startswith("ollama/"):
            api_base = effective_keys.get("ollama_base_url", "http://localhost:11434")
        elif model.startswith("custom/"):
            api_base = effective_keys.get("custom_base_url")
            model = model.replace("custom/", "")

        return messages, model, api_base, effective_keys.get(self._get_provider(model)), is_local

    async def _stream_llm(
        self, model: str, prompt: str, system_prompt: Optional[str],
        temperature: float, max_tokens: int, tenant_api_keys: Optional[dict],
        usage_sink: dict,
    ):
        """Yield content deltas from one model, filling ``usage_sink`` at the end.

        Same preflight as ``_call_llm`` (see ``_prepare_call``), same fail-closed
        behaviour when no provider is reachable. Usage arrives on a final chunk
        via ``stream_options``, so a streamed call is metered exactly like a
        blocking one rather than quietly escaping the cost ledger.
        """
        if not await self.provider_available(tenant_api_keys):
            from app.core.config import get_settings
            if not get_settings().simulated_llm_allowed:
                raise NoLLMProviderError(
                    "No LLM provider is reachable (no cloud key, no local Ollama) "
                    "and ALLOW_SIMULATED_LLM is off. Refusing to fabricate a "
                    "governance decision."
                )
            yield self._simulated_completion(prompt, system_prompt)["content"]
            return

        messages, model, api_base, api_key, is_local = await self._prepare_call(
            model, prompt, system_prompt, tenant_api_keys
        )

        import litellm
        from app.core.config import get_settings as _get_cfg
        _cfg = _get_cfg()
        response = await litellm.acompletion(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            api_base=api_base,
            api_key=api_key,
            timeout=_cfg.LLM_LOCAL_TIMEOUT_SECONDS if is_local else _cfg.LLM_TIMEOUT_SECONDS,
            stream=True,
            stream_options={"include_usage": True},
        )
        usage_sink.setdefault("model", model)
        async for chunk in response:
            u = getattr(chunk, "usage", None)
            if u is not None:
                usage_sink["prompt_tokens"] = getattr(u, "prompt_tokens", 0) or 0
                usage_sink["completion_tokens"] = getattr(u, "completion_tokens", 0) or 0
                usage_sink["total_tokens"] = getattr(u, "total_tokens", 0) or 0
            try:
                delta = chunk.choices[0].delta.content
            except (AttributeError, IndexError):
                delta = None
            if delta:
                yield delta

    # ── Simulated (no-provider) responses ────────────────────────────────

    def _simulated_completion(self, prompt: str, system_prompt: Optional[str]) -> dict:
        # Deterministic degraded-mode payload; logic lives in llm_simulation.
        return simulated_completion(prompt, system_prompt)

    def embedding_metadata(self) -> dict:
        """Provenance to stamp on every upserted vector.

        ``embedding_model`` records which model produced the vector (from the most
        recent embed() call) so a later pass can detect and re-embed stale vectors
        after a model change; ``simulated`` marks non-semantic pseudo-vectors (no
        real provider) so search can exclude or down-weight them.
        """
        return {
            "embedding_model": self.last_embedding_model,
            "simulated": bool(self.embeddings_simulated),
        }

    async def _resolve_embedding_model(
        self, model: str, tenant_api_keys: Optional[dict] = None
    ) -> tuple[str, Optional[str]]:
        """Pick the embedding model actually used, returning ``(model, api_base)``.

        The documented dev-path limitation was that a zero-key SQLite stack fell
        back to non-semantic pseudo-vectors even with a local Ollama running. Here,
        when the requested cloud model has no usable key AND we are on the SQLite
        dev path AND a local Ollama is reachable, we route to the local
        ``nomic-embed-text`` model so dev semantic search uses REAL embeddings.

        Scoped to SQLite on purpose: the pgvector table is a fixed dimension, so we
        never silently change embedding dimensionality on a Postgres deployment.
        """
        from app.core.config import get_settings
        settings = get_settings()
        effective = self._effective_keys(tenant_api_keys)
        default_base = getattr(settings, "OLLAMA_BASE_URL", None) or "http://localhost:11434"

        if model.startswith("ollama/"):
            return model, effective.get("ollama_base_url", default_base)
        if effective.get(self._get_provider(model)) or effective.get("custom_base_url"):
            return model, None  # a real cloud key is configured — use it
        if getattr(settings, "is_sqlite", False):
            base = effective.get("ollama_base_url", default_base)
            if await _ollama_reachable(base):
                local = self.MODEL_TIERS.get("embedding", "ollama/nomic-embed-text:latest")
                logger.info("[LLM] No key for %s; routing embeddings to local %s", model, local)
                return local, base
        return model, None

    async def embed(
        self,
        texts: list[str],
        model: str = "text-embedding-3-small",
        tenant_api_keys: Optional[dict] = None,
    ) -> list[list[float]]:
        """Generate embeddings using the configured embedding model.

        On the zero-key SQLite dev stack, prefers a reachable local Ollama
        embedding model over non-semantic pseudo-vectors (see
        ``_resolve_embedding_model``). Falls back to deterministic seeded
        pseudo-vectors (unit-normalized, correct dimension) only when no provider
        is available at all. Sets ``self.embeddings_simulated``.
        """
        model, api_base = await self._resolve_embedding_model(model, tenant_api_keys)
        self.last_embedding_model = model
        dim = embedding_dim(model)

        if not await self.provider_available(tenant_api_keys):
            self.embeddings_simulated = True
            logger.info(f"[LLM] No provider available — returning SIMULATED embeddings (dim={dim}).")
            return [pseudo_embedding(t, dim) for t in texts]

        # Serve cache hits (byte-identical) and only embed the misses. A fully
        # cached batch skips the provider call entirely.
        keys = [_embed_key(model, t) for t in texts]
        results: list = [None] * len(texts)
        miss_idx: list[int] = []
        for i, k in enumerate(keys):
            cached = _embed_cache_get(k)
            if cached is not None:
                results[i] = cached
            else:
                miss_idx.append(i)
        if not miss_idx:
            self.embeddings_simulated = False
            return results
        _EMBED_CACHE_STATS["misses"] += len(miss_idx)

        try:
            import litellm
            effective_keys = {**self.api_keys, **(tenant_api_keys or {})}

            _t0 = time.perf_counter()
            from app.core.config import get_settings as _get_cfg
            _cfg = _get_cfg()
            response = await litellm.aembedding(
                model=model,
                input=[texts[i] for i in miss_idx],
                api_key=effective_keys.get(self._get_provider(model)),
                api_base=api_base,
                timeout=(
                    _cfg.LLM_LOCAL_TIMEOUT_SECONDS
                    if model.startswith(("ollama/", "custom/"))
                    else _cfg.LLM_TIMEOUT_SECONDS
                ),
            )
            self.embeddings_simulated = False
            usage = getattr(response, "usage", None)
            await self._record_cost(
                model=model,
                model_tier="embedding",
                usage={
                    "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                    "completion_tokens": 0,
                    "total_tokens": getattr(usage, "total_tokens", 0) or 0,
                } if usage else {},
                latency_ms=int((time.perf_counter() - _t0) * 1000),
            )
            for pos, item in zip(miss_idx, response.data):
                vec = item["embedding"]
                results[pos] = vec
                _embed_cache_put(keys[pos], vec)
            return results
        except ImportError:
            logger.warning("LiteLLM not installed — returning simulated embeddings")
            self.embeddings_simulated = True
            return [pseudo_embedding(t, dim) for t in texts]
        except Exception as e:
            logger.error(f"Embedding failed: {e} — falling back to simulated embeddings")
            self.embeddings_simulated = True
            return [pseudo_embedding(t, dim) for t in texts]

    @staticmethod
    def _get_provider(model: str) -> str:
        if model.startswith(("gpt-", "text-embedding", "o1", "o3")): return "openai"
        elif model.startswith(("claude-",)): return "anthropic"
        elif model.startswith(("mistral",)): return "mistral"
        elif model.startswith(("command",)): return "cohere"
        elif model.startswith(("groq/", "llama")): return "groq"
        elif model.startswith("ollama/"): return "ollama"
        return "openai"

    @staticmethod
    def list_supported_providers() -> list[dict]:
        return [
            {"id": "openai", "name": "OpenAI", "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "o1", "o3-mini"], "requires_key": True},
            {"id": "anthropic", "name": "Anthropic", "models": ["claude-sonnet-4-20250514", "claude-3-5-haiku-20241022", "claude-3-opus-20240229"], "requires_key": True},
            {"id": "mistral", "name": "Mistral AI", "models": ["mistral-large-latest", "mistral-medium", "mistral-small"], "requires_key": True},
            {"id": "groq", "name": "Groq", "models": ["groq/llama-3.3-70b-versatile", "groq/mixtral-8x7b-32768"], "requires_key": True},
            {"id": "cohere", "name": "Cohere", "models": ["command-r-plus", "command-r"], "requires_key": True},
            {"id": "ollama", "name": "Ollama (Self-hosted)", "models": ["ollama/llama3", "ollama/mistral"], "requires_key": False},
            {"id": "custom", "name": "Custom OpenAI-compatible", "models": [], "requires_key": True},
        ]

    @staticmethod
    def list_embedding_models() -> list[dict]:
        return [
            {"id": "text-embedding-3-small", "provider": "openai", "dimensions": 1536},
            {"id": "text-embedding-3-large", "provider": "openai", "dimensions": 3072},
            {"id": "embed-english-v3.0", "provider": "cohere", "dimensions": 1024},
        ]


async def get_tenant_router(tenant_id: Optional[str] = None) -> LLMRouter:
    """Resolve an LLM router bound to the current tenant's fine-tuned models (BYOK).

    Uses the ambient ``current_tenant_id`` when no id is passed (the same
    request-scoped contextvar cost metering and the budget gate already read), so
    the tenant's promoted/fine-tuned models actually reach the call site instead
    of the bare platform defaults. Falls back to a default router when there is no
    tenant context — system jobs, boot probes — so those paths never break.
    """
    tid = tenant_id or current_tenant_id.get()
    if not tid:
        return LLMRouter()
    return await LLMRouter.for_tenant(tid)
