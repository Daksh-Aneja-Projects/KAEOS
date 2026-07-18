"""
KAEOS S1 N1 — Model Management Service
4-tier model routing, A/B canary testing, prompt registry, token budget calculator.
"""
import logging
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.infrastructure import (
    ModelRegistryEntry, ModelTier, PromptTemplate
)

logger = logging.getLogger(__name__)


class ModelManagementService:
    """
    N1 — Model Management
    Catalogs all deployed LLM models with versions, performance benchmarks,
    and cost profiles. Routes requests to appropriate tier automatically.
    """

    # Default tier routing map
    TIER_USE_CASES = {
        ModelTier.FAST: [
            "pii_classification", "schema_mapping", "extraction_clustering",
            "faq_response", "formatting", "status_check"
        ],
        ModelTier.STANDARD: [
            "agent_orchestration", "ooda_orient", "base_reasoning",
            "conflict_detection", "compliance_check", "intent_routing"
        ],
        ModelTier.DEEP: [
            "debate_engine", "cfo_agent", "ethical_ai_assessment",
            "pioneer_analysis", "blueprint_generation", "simulation"
        ],
        ModelTier.VERTICAL: [
            "domain_extraction", "vertical_classification"
        ]
    }

    @staticmethod
    async def register_model(
        db: AsyncSession,
        tenant_id: str,
        model_name: str,
        provider: str,
        tier: ModelTier,
        cost_per_1k_input: float = 0.0,
        cost_per_1k_output: float = 0.0,
        max_context_window: int = 200000,
        use_cases: list = None,
        is_canary: bool = False
    ) -> dict:
        """Register a new model in the catalog."""
        entry = ModelRegistryEntry(
            tenant_id=tenant_id,
            model_name=model_name,
            provider=provider,
            tier=tier,
            cost_per_1k_input=cost_per_1k_input,
            cost_per_1k_output=cost_per_1k_output,
            max_context_window=max_context_window,
            use_cases=use_cases or [],
            is_canary=is_canary
        )
        db.add(entry)
        await db.commit()
        await db.refresh(entry)
        logger.info(f"[N1] Registered model {model_name} ({provider}) tier={tier.value}")
        return {
            "id": entry.id,
            "model_name": entry.model_name,
            "provider": entry.provider,
            "tier": entry.tier.value,
            "is_canary": entry.is_canary
        }

    @staticmethod
    async def route_to_model(
        db: AsyncSession,
        tenant_id: str,
        request_type: str,
        preferred_tier: Optional[ModelTier] = None
    ) -> dict:
        """
        Route a reasoning request to the appropriate model tier.
        Uses request_type to classify complexity and selects best available model.
        """
        # Determine tier from request type if not specified
        target_tier = preferred_tier
        if not target_tier:
            for tier, use_cases in ModelManagementService.TIER_USE_CASES.items():
                if request_type in use_cases:
                    target_tier = tier
                    break
            if not target_tier:
                target_tier = ModelTier.STANDARD

        # Find best available model for tier
        result = await db.execute(
            select(ModelRegistryEntry)
            .where(
                ModelRegistryEntry.tenant_id == tenant_id,
                ModelRegistryEntry.tier == target_tier,
                ModelRegistryEntry.is_active == True
            )
            .order_by(ModelRegistryEntry.success_rate.desc())
        )
        models = result.scalars().all()

        if not models:
            # Fallback: try one tier down
            fallback_order = [ModelTier.STANDARD, ModelTier.FAST, ModelTier.DEEP]
            for fb_tier in fallback_order:
                if fb_tier != target_tier:
                    result = await db.execute(
                        select(ModelRegistryEntry)
                        .where(
                            ModelRegistryEntry.tenant_id == tenant_id,
                            ModelRegistryEntry.tier == fb_tier,
                            ModelRegistryEntry.is_active == True
                        )
                        .order_by(ModelRegistryEntry.success_rate.desc())
                    )
                    models = result.scalars().all()
                    if models:
                        break

        if not models:
            return {
                "model_name": "claude-sonnet-4-20250514",
                "provider": "anthropic",
                "tier": "STANDARD",
                "source": "default_fallback"
            }

        # A/B canary routing: deterministic 10% based on tenant_id hash (reproducible, auditable)
        import hashlib
        canary = [m for m in models if m.is_canary]
        primary = [m for m in models if not m.is_canary]

        # Use tenant_id hash to assign 10% to canary — same tenant always gets same model
        tenant_hash_pct = int(hashlib.sha256(tenant_id.encode()).hexdigest()[:2], 16) / 255.0
        if canary and tenant_hash_pct < 0.10:
            selected = canary[0]
        elif primary:
            selected = primary[0]
        else:
            selected = models[0]

        return {
            "model_name": selected.model_name,
            "provider": selected.provider,
            "tier": selected.tier.value,
            "is_canary": selected.is_canary,
            "source": "registry_routed"
        }

    @staticmethod
    async def get_registry(db: AsyncSession, tenant_id: str) -> list:
        """List all registered models for a tenant."""
        result = await db.execute(
            select(ModelRegistryEntry)
            .where(ModelRegistryEntry.tenant_id == tenant_id)
            .order_by(ModelRegistryEntry.tier, ModelRegistryEntry.model_name)
        )
        models = result.scalars().all()
        return [{
            "id": m.id,
            "model_name": m.model_name,
            "provider": m.provider,
            "tier": m.tier.value,
            "is_active": m.is_active,
            "is_canary": m.is_canary,
            "avg_latency_ms": m.avg_latency_ms,
            "success_rate": m.success_rate,
            "cost_per_1k_input": m.cost_per_1k_input,
            "cost_per_1k_output": m.cost_per_1k_output,
            "max_context_window": m.max_context_window,
            "use_cases": m.use_cases,
            "created_at": str(m.created_at) if m.created_at else None
        } for m in models]

    @staticmethod
    async def update_model_stats(
        db: AsyncSession,
        model_name: str,
        tenant_id: str,
        latency_ms: int,
        success: bool
    ):
        """Update model performance stats after each call."""
        result = await db.execute(
            select(ModelRegistryEntry).where(
                ModelRegistryEntry.model_name == model_name,
                ModelRegistryEntry.tenant_id == tenant_id
            )
        )
        model = result.scalar_one_or_none()
        if model:
            # Running average for latency
            if model.avg_latency_ms == 0:
                model.avg_latency_ms = latency_ms
            else:
                model.avg_latency_ms = int(model.avg_latency_ms * 0.9 + latency_ms * 0.1)
            # Exponential moving average for success rate
            model.success_rate = model.success_rate * 0.95 + (1.0 if success else 0.0) * 0.05
            await db.commit()

    # ── Prompt Registry ───────────────────────────────────────────────────────

    @staticmethod
    async def register_prompt(
        db: AsyncSession,
        tenant_id: str,
        template_key: str,
        system_prompt: str,
        user_template: str = None,
        model_tier: ModelTier = ModelTier.STANDARD,
        max_tokens: int = 4096,
        temperature: float = 0.7
    ) -> dict:
        """Register or update a versioned prompt template."""
        # Check for existing active template
        result = await db.execute(
            select(PromptTemplate).where(
                PromptTemplate.tenant_id == tenant_id,
                PromptTemplate.template_key == template_key,
                PromptTemplate.is_active == True
            )
        )
        existing = result.scalar_one_or_none()
        new_version = 1
        if existing:
            existing.is_active = False
            new_version = existing.version + 1

        template = PromptTemplate(
            tenant_id=tenant_id,
            template_key=template_key,
            version=new_version,
            system_prompt=system_prompt,
            user_template=user_template,
            model_tier=model_tier,
            max_tokens=max_tokens,
            temperature=temperature
        )
        db.add(template)
        await db.commit()
        await db.refresh(template)
        return {
            "id": template.id,
            "template_key": template.template_key,
            "version": template.version
        }

    @staticmethod
    async def get_prompt(
        db: AsyncSession,
        tenant_id: str,
        template_key: str
    ) -> Optional[dict]:
        """Get the active prompt template for a key."""
        result = await db.execute(
            select(PromptTemplate).where(
                PromptTemplate.tenant_id == tenant_id,
                PromptTemplate.template_key == template_key,
                PromptTemplate.is_active == True
            )
        )
        t = result.scalar_one_or_none()
        if not t:
            return None
        return {
            "id": t.id,
            "template_key": t.template_key,
            "version": t.version,
            "system_prompt": t.system_prompt,
            "user_template": t.user_template,
            "model_tier": t.model_tier.value,
            "max_tokens": t.max_tokens,
            "temperature": t.temperature
        }

    @staticmethod
    async def list_prompts(db: AsyncSession, tenant_id: str) -> list:
        """List all active prompt templates."""
        result = await db.execute(
            select(PromptTemplate).where(
                PromptTemplate.tenant_id == tenant_id,
                PromptTemplate.is_active == True
            ).order_by(PromptTemplate.template_key)
        )
        templates = result.scalars().all()
        return [{
            "id": t.id,
            "template_key": t.template_key,
            "version": t.version,
            "model_tier": t.model_tier.value,
            "usage_count": t.usage_count,
            "avg_quality_score": t.avg_quality_score
        } for t in templates]

    @staticmethod
    async def estimate_token_budget(request_type: str, payload_size: int = 0) -> dict:
        """Pre-compute expected token usage per workflow type."""
        # Baseline estimates per request type
        estimates = {
            "extraction": {"input": 2000, "output": 500, "cost_est": 0.003},
            "debate": {"input": 8000, "output": 3000, "cost_est": 0.04},
            "orchestration": {"input": 4000, "output": 1500, "cost_est": 0.015},
            "compliance_check": {"input": 3000, "output": 800, "cost_est": 0.008},
            "simulation": {"input": 6000, "output": 2000, "cost_est": 0.025},
            "blueprint_generation": {"input": 5000, "output": 2500, "cost_est": 0.02},
            "pii_classification": {"input": 1000, "output": 200, "cost_est": 0.001},
        }
        base = estimates.get(request_type, {"input": 2000, "output": 500, "cost_est": 0.005})
        # Scale by payload
        scale = max(1.0, payload_size / 1000)
        return {
            "request_type": request_type,
            "estimated_input_tokens": int(base["input"] * scale),
            "estimated_output_tokens": int(base["output"] * scale),
            "estimated_cost_usd": round(base["cost_est"] * scale, 4),
            "within_budget": True
        }
