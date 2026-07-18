"""KAEOS — Pydantic Schemas: Rules"""
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class ConfidenceTierEnum(str, Enum):
    SPECULATIVE = "SPECULATIVE"
    INFERRED = "INFERRED"
    VALIDATED_PEER = "VALIDATED_PEER"
    VALIDATED_MANAGER = "VALIDATED_MANAGER"
    VALIDATED_DH = "VALIDATED_DH"
    VERIFIED = "VERIFIED"


class ConfidenceVectorSchema(BaseModel):
    source_breadth: float = 0.0
    source_authority: float = 0.0
    temporal_freshness: float = 1.0
    outcome_validation: float = 0.5
    explicit_validation: float = 0.0


class RuleCreate(BaseModel):
    statement: str
    trigger_json: Dict[str, Any]
    action_json: Dict[str, Any]
    domain: Optional[str] = None
    workflow_id: Optional[str] = None
    exceptions_json: List[Any] = []
    compliance_tags: List[str] = []
    half_life_days: int = 180
    access_level: str = "department"


class RuleUpdate(BaseModel):
    statement: Optional[str] = None
    trigger_json: Optional[Dict[str, Any]] = None
    action_json: Optional[Dict[str, Any]] = None
    confidence_tier: Optional[ConfidenceTierEnum] = None
    is_executable: Optional[bool] = None
    is_archived: Optional[bool] = None


class RuleResponse(BaseModel):
    id: str
    tenant_id: str
    statement: str
    trigger_json: Dict[str, Any]
    action_json: Dict[str, Any]
    exceptions_json: List[Any] = []
    domain: Optional[str] = None
    workflow_id: Optional[str] = None
    confidence_vector: Dict[str, float] = {}
    confidence_scalar: float
    confidence_tier: str
    half_life_days: int
    is_executable: bool
    is_archived: bool
    version: int
    compliance_tags: List[str] = []
    access_level: str
    created_at: Optional[datetime] = None
    validated_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    last_decay_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class RuleValidateRequest(BaseModel):
    validator_role: str = "dept_head"
    validator_hash: str = "validator_001"
    new_tier: ConfidenceTierEnum = ConfidenceTierEnum.VALIDATED_DH


class RuleListResponse(BaseModel):
    total: int
    rules: List[RuleResponse]
