"""KAEOS — Pydantic Schemas: Dashboard & Observability"""
from pydantic import BaseModel
from typing import List, Dict, Any, Optional


class DepartmentCoverage(BaseModel):
    department: str
    coverage: float
    rule_count: int
    trend: str = "stable"  # up, down, stable


class ConfidenceDistribution(BaseModel):
    speculative: float = 0.0
    inferred: float = 0.0
    validated_peer: float = 0.0
    validated_dh: float = 0.0
    verified: float = 0.0


class DecayAlert(BaseModel):
    rule_id: str
    statement: str
    domain: str
    current_confidence: float
    days_since_validation: int
    half_life_days: int
    urgency: str  # CRITICAL, WARNING, INFO


class AgentMetrics(BaseModel):
    total_executions_7d: int
    success_rate: float
    rag_fallback_rate: float
    human_overrides: int
    avg_duration_ms: int
    skills_used: int


class ElicitationMetrics(BaseModel):
    questions_sent_7d: int
    response_rate: float
    entries_created: int
    avg_time_to_answer_hours: float
    top_contributors: List[Dict[str, Any]] = []


class KBHealthResponse(BaseModel):
    overall_score: int
    score_trend: str  # up, down, stable
    total_rules: int
    total_skills: int
    total_executions: int
    coverage: List[DepartmentCoverage]
    confidence_distribution: ConfidenceDistribution
    decay_alerts: List[DecayAlert]
    agent_metrics: AgentMetrics
    elicitation_metrics: ElicitationMetrics
    freshness: Dict[str, float]  # within_half_life, decaying, expired


class ComplianceStatus(BaseModel):
    framework: str
    coverage_pct: float
    violations: int
    blocker_count: int
    last_audit: Optional[str] = None
    status: str  # COMPLIANT, REVIEW, NOT_APPLICABLE


class ComplianceDashboardResponse(BaseModel):
    frameworks: List[ComplianceStatus]
    total_tagged_rules: int
    untagged_rules: int
