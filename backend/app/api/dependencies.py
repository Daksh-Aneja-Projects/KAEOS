from app.services.llm_router import LLMRouter, get_tenant_router

# Simple Dependency Injection container to decouple instantiations

async def get_llm_router() -> LLMRouter:
    """Tenant-aware router: resolves the caller's tenant (from the ambient
    request context) and returns a BYOK router bound to that tenant's fine-tuned
    models, falling back to a bare router for system jobs with no tenant."""
    return await get_tenant_router()
