"""KAEOS 10X — Polymorphic Operations API"""
import hashlib

from app.core.tenant import require_role
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.core.database import get_db
from app.services.polymorphic_engine import PolymorphicEngine

router = APIRouter(prefix="/polymorphic", tags=["KAEOS 10X — Polymorphic Engine"])

class SynthesisRequest(BaseModel):
    skill_id: str
    missing_integration: str

@router.post("/synthesize")
async def synthesize_tool(request: SynthesisRequest, tenant: dict = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)):
    """
    Executes the polymorphic engine to autonomously write
    and deploy code bridging a missing tool integration gap.

    Requires admin role — this autonomously generates and deploys code and
    mutates a Skill, the highest-consequence action class on the platform.
    """
    tenant_id = tenant["tenant_id"]
    try:
        # Scope the mutated Skill lookup to the caller's tenant.
        result = await PolymorphicEngine.auto_patch_skill(
            db=db,
            skill_id=request.skill_id,
            missing_integration=request.missing_integration,
            tenant_id=tenant_id,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class UIRequest(BaseModel):
    persona: str  # e.g., "CFO", "Data Analyst", "Sales Rep"
    intent: str
    data_context: dict

@router.post("/ambient-ui")
async def generate_ambient_ui(request: UIRequest):
    """
    L25 Polymorphic Ambient Interface:
    Generates a transient, highly-personalized React component based on the user's cognitive style.
    This component is intended to be injected directly into Slack, Teams, or rendered ambiently.
    """
    from app.services.llm_router import LLMRouter
    router = LLMRouter()
    
    prompt = (
        f"You are the KAEOS Polymorphic UI Engine. Generate a transient React component (JSX using TailwindCSS) "
        f"that perfectly suits the cognitive style of a {request.persona} for the intent: {request.intent}.\n"
        f"If CFO: Prefer dense financial metrics, ROI, and risk charts.\n"
        f"If Data Analyst: Prefer raw data tables, distributions, and confidence intervals.\n"
        f"If Sales: Prefer high-impact visuals, win-probability, and quick-action buttons.\n"
        f"Data context: {request.data_context}\n"
        f"Output ONLY the raw JSX code for the component. No markdown wrapping."
    )
    
    response = await router.complete(
        prompt=prompt,
        model_tier="fast",
    )
    
    content = response if isinstance(response, str) else response.get("content", "")
    jsx_content = content.replace("```jsx", "").replace("```", "").strip()
    
    return {
        "status": "success",
        "transient_component_id": "ambient_ui_" + hashlib.sha256(jsx_content.encode()).hexdigest()[:8],
        "jsx_payload": jsx_content,
        "render_target": "slack_block_kit_or_web"
    }
