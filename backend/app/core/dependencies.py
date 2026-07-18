from app.services.llm_router import LLMRouter
from app.services.knowledge import PolystoreEngine

# Simple Dependency Injection container to decouple instantiations

def get_llm_router() -> LLMRouter:
    return LLMRouter()

def get_polystore_engine() -> PolystoreEngine:
    return PolystoreEngine()
