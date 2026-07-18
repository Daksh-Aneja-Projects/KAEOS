"""KAEOS — Agent Factory Schemas (Pydantic request/response models)"""
from pydantic import BaseModel, Field
from typing import Optional


class BlueprintCreateRequest(BaseModel):
    prompt: str = Field(..., description="Natural language description of the agent")
    created_by: Optional[str] = None


class BlueprintRefineRequest(BaseModel):
    blueprint_graph: Optional[dict] = None
    name: Optional[str] = None
    mcp_tools_required: Optional[list] = None


class BlueprintApproveRequest(BaseModel):
    approved_by: Optional[str] = None


class DeployRequest(BaseModel):
    trigger_config: Optional[dict] = None


class MarkReadRequest(BaseModel):
    event_ids: list[str]


class FairnessOverrideRequest(BaseModel):
    override_by: str
    justification: str


class CalendarEventRequest(BaseModel):
    name: str
    calendar_type: str = "CUSTOM"
    description: Optional[str] = None
    start_date: str
    end_date: str
    recurrence_rule: Optional[str] = None
    department: Optional[str] = None
    priority_boost_pct: float = 40.0
    is_blocking: bool = False
