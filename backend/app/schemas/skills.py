"""KAEOS — Pydantic Schemas: Skills"""
from pydantic import BaseModel, model_validator
from typing import Optional, List, Dict, Any
from datetime import datetime


class SkillStep(BaseModel):
    """One executable step of a skill contract.

    Two authored shapes are accepted (workforce `action` and domain-agent
    `prompt`/`name`), but the INSTRUCTION TEXT must exist in at least one of
    them - a step without it reaches the model as ACTION "unknown" and fails
    silently (found live: the executor dropped `prompt` for months).
    """
    model_config = {"extra": "allow"}

    id: Optional[str] = None
    step: Optional[int] = None
    name: Optional[str] = None
    action: Optional[str] = None
    prompt: Optional[str] = None
    tool: Optional[str] = None
    # condition/thresholds are free-form: the compiler emits structured dicts
    # (e.g. {"condition": "refund_amount < 50"}) - only instruction presence
    # is contract-enforced here.
    condition: Optional[Any] = None
    thresholds: Optional[Any] = None

    @model_validator(mode="after")
    def _must_carry_instruction(self):
        text = self.action or self.prompt or self.name
        if not text or not str(text).strip():
            raise ValueError(
                "step carries no instruction text: set 'action', 'prompt', or 'name'"
            )
        return self


def validate_steps(steps: List[Any]) -> List[Dict[str, Any]]:
    """Validate authored steps; raises ValueError naming the offending step."""
    validated = []
    for i, raw in enumerate(steps or []):
        if not isinstance(raw, dict):
            raise ValueError(f"step {i + 1} must be an object, got {type(raw).__name__}")
        try:
            validated.append(SkillStep(**raw).model_dump(exclude_none=True))
        except Exception as e:
            raise ValueError(f"step {i + 1} invalid: {e}") from e
    return validated


class SkillSummary(BaseModel):
    id: str
    skill_id: str
    department: str
    domain: str
    version: str
    status: str
    confidence: float
    confidence_tier: str
    execution_count: int
    success_rate: float
    half_life_days: int
    expires_at: Optional[datetime] = None
    last_validated: Optional[datetime] = None
    mcp_tool_bindings: List[str] = []
    compliance_tags: List[str] = []
    access_level: str = "department"

    class Config:
        from_attributes = True


class SkillDetail(SkillSummary):
    confidence_vector: Dict[str, float] = {}
    triggers: List[Any] = []
    steps: List[Any] = []
    exceptions: List[Any] = []
    guardrails: Dict[str, Any] = {}
    confidence_notes: List[str] = []
    provenance: Dict[str, Any] = {}
    compiled_at: Optional[datetime] = None


class SkillRegistryResponse(BaseModel):
    total: int
    total_executions: int
    avg_success_rate: float
    skills: List[SkillSummary]


class SkillExecutionRequest(BaseModel):
    intent: str
    context: Dict[str, Any] = {}


class SkillExecutionResponse(BaseModel):
    execution_id: str
    skill_id: str
    status: str
    route_type: str
    reasoning_chain: List[Dict[str, Any]] = []
    duration_ms: int = 0
    hitl_required: bool = False
