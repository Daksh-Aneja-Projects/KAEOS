"""
KAEOS Intelligence Metrics Models
Stores the historical accuracy of predictions, recommendations, and simulations for Trust Calibration.
"""

from datetime import datetime, timezone
import uuid

from sqlalchemy import String, DateTime, Float, Text, JSON, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

class PredictionRecord(Base):
    __tablename__ = "trust_predictions"
    
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    
    prediction_type: Mapped[str] = mapped_column(String)
    target_entity: Mapped[str] = mapped_column(String)
    confidence: Mapped[float] = mapped_column(Float)
    
    # Cognitive Versioning
    model_version: Mapped[str] = mapped_column(String, default="v1.0.0")
    
    reasoning_path: Mapped[str] = mapped_column(Text)
    expected_outcome: Mapped[str] = mapped_column(Text)
    
    actual_outcome: Mapped[str] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, default="PENDING") # PENDING, CORRECT, INCORRECT, PARTIAL
    
    calibration_error: Mapped[float] = mapped_column(Float, nullable=True)
    brier_score: Mapped[float] = mapped_column(Float, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    resolution_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)


class RecommendationRecord(Base):
    __tablename__ = "trust_recommendations"
    
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    
    recommendation: Mapped[str] = mapped_column(Text)
    reasoning: Mapped[str] = mapped_column(Text)
    
    # Cognitive Versioning
    model_version: Mapped[str] = mapped_column(String, default="v1.0.0")
    
    expected_benefit: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="PENDING") # PENDING, ACCEPTED, REJECTED
    
    actual_result: Mapped[str] = mapped_column(Text, nullable=True)
    success_score: Mapped[float] = mapped_column(Float, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    resolution_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)


class ValidationLedger(Base):
    __tablename__ = "trust_validation_ledger"
    """Tracks simulation and causal validation."""
    
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    
    validation_type: Mapped[str] = mapped_column(String) # SIMULATION, CAUSAL
    source_event: Mapped[str] = mapped_column(String)
    
    predicted_state: Mapped[dict] = mapped_column(JSON)
    actual_state: Mapped[dict] = mapped_column(JSON, nullable=True)
    
    accuracy_score: Mapped[float] = mapped_column(Float, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class TrustMetrics(Base):
    __tablename__ = "trust_enterprise_metrics"
    """The live aggregation of trust for a tenant."""
    
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String, index=True, unique=True)
    
    prediction_trust: Mapped[float] = mapped_column(Float, default=1.0)
    recommendation_trust: Mapped[float] = mapped_column(Float, default=1.0)
    simulation_trust: Mapped[float] = mapped_column(Float, default=1.0)
    causal_trust: Mapped[float] = mapped_column(Float, default=1.0)
    
    enterprise_trust_score: Mapped[float] = mapped_column(Float, default=1.0)
    
    total_predictions: Mapped[int] = mapped_column(Integer, default=0)
    brier_score_avg: Mapped[float] = mapped_column(Float, default=0.0)
    
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

class DecisionRecord(Base):
    __tablename__ = "trust_decisions"
    """Decision Ledger storing historical memory of all twin and human actions."""
    
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    
    context: Mapped[str] = mapped_column(Text)
    options_considered: Mapped[dict] = mapped_column(JSON)
    recommendation: Mapped[str] = mapped_column(Text)
    selected_action: Mapped[str] = mapped_column(Text)
    decision_maker: Mapped[str] = mapped_column(String) # SYSTEM, USER, AGENT
    
    # Tier tracking
    evaluation_tier: Mapped[int] = mapped_column(Integer, default=1) # 1 = Fast, 2 = Deep Simulation
    
    # Decision Scoring
    decision_score: Mapped[float] = mapped_column(Float, nullable=True)
    expected_value: Mapped[float] = mapped_column(Float, nullable=True)
    risk_score: Mapped[float] = mapped_column(Float, nullable=True)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=True)
    decision_quality_score: Mapped[float] = mapped_column(Float, nullable=True)
    
    # Outcomes
    expected_outcome: Mapped[str] = mapped_column(Text)
    actual_outcome: Mapped[str] = mapped_column(Text, nullable=True)
    success_score: Mapped[float] = mapped_column(Float, nullable=True)
    
    # Regret Tracking
    decision_regret: Mapped[float] = mapped_column(Float, nullable=True) # Best Alternative Actual - Selected Actual
    percentage_regret: Mapped[float] = mapped_column(Float, nullable=True)
    goal_regret: Mapped[float] = mapped_column(Float, nullable=True)
    risk_regret: Mapped[float] = mapped_column(Float, nullable=True)
    financial_regret: Mapped[float] = mapped_column(Float, nullable=True)
    
    # Traceability links
    linked_prediction_ids: Mapped[list] = mapped_column(JSON, default=[])
    linked_recommendation_ids: Mapped[list] = mapped_column(JSON, default=[])
    linked_simulation_ids: Mapped[list] = mapped_column(JSON, default=[])
    linked_causal_chains: Mapped[list] = mapped_column(JSON, default=[])
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    resolution_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)

class DecisionTrace(Base):
    """
    Enterprise Memory: End-to-end traceability of why a decision was recommended and what happened.
    Event -> Prediction -> Causal Chain -> Generated Options -> Constraints -> Simulation -> Selection -> Outcome -> Regret
    """
    __tablename__ = "decision_traces"

    trace_id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    
    # Trace Links
    source_event: Mapped[str] = mapped_column(String)
    prediction_id: Mapped[str] = mapped_column(String, nullable=True)
    causal_chain_id: Mapped[str] = mapped_column(String, nullable=True)
    decision_record_id: Mapped[str] = mapped_column(String) # Link to the selected DecisionRecord
    
    # Trace payloads
    generated_options: Mapped[list] = mapped_column(JSON) # Snapshot of all Option A, B, C evaluated
    constraint_evaluations: Mapped[dict] = mapped_column(JSON) # Snapshot of policy/budget constraints applied
    simulation_results: Mapped[dict] = mapped_column(JSON) # Snapshot of 10-dimensional deep evaluation
    
    # Reasoning
    executive_summary: Mapped[str] = mapped_column(Text)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class EnterpriseFitnessRecord(Base):
    """
    Tracks the continuous health and capability optimization of the enterprise graph.
    """
    __tablename__ = "evolution_fitness"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    
    global_fitness_score: Mapped[float] = mapped_column(Float)
    
    organizational_fitness: Mapped[float] = mapped_column(Float)
    workforce_fitness: Mapped[float] = mapped_column(Float)
    portfolio_fitness: Mapped[float] = mapped_column(Float)
    vendor_fitness: Mapped[float] = mapped_column(Float)
    financial_fitness: Mapped[float] = mapped_column(Float)
    execution_fitness: Mapped[float] = mapped_column(Float)
    goal_alignment_fitness: Mapped[float] = mapped_column(Float)
    risk_fitness: Mapped[float] = mapped_column(Float)
    capability_fitness: Mapped[float] = mapped_column(Float, default=1.0)
    
    factors: Mapped[dict] = mapped_column(JSON) # Detailed contributing, positive, negative factors
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class EnterpriseGenome(Base):
    """
    Enterprise Genome: Represents a distinct version of the enterprise structure and state over time.
    Version N -> Optimization -> Version N+1
    """
    __tablename__ = "evolution_genome"
    
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    
    fitness_record_id: Mapped[str] = mapped_column(String) # Link to fitness scores at this version
    
    # State snapshot (Structure, Capabilities, Workforce, etc)
    state_snapshot: Mapped[dict] = mapped_column(JSON)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class EvolutionMemory(Base):
    """
    Stores historical organizational changes recommended by the Evolution Engine.
    """
    __tablename__ = "evolution_memory"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    
    source_genome_id: Mapped[str] = mapped_column(String, nullable=True)
    target_genome_id: Mapped[str] = mapped_column(String, nullable=True)
    
    recommendation_type: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text)
    
    expected_improvement: Mapped[float] = mapped_column(Float)
    expected_cost: Mapped[float] = mapped_column(Float)
    expected_risk: Mapped[float] = mapped_column(Float)
    simulated_fitness_delta: Mapped[float] = mapped_column(Float)
    
    # Recommendation Context
    similarity_evidence: Mapped[dict] = mapped_column(JSON, nullable=True) # Similar genome IDs and scores
    counterfactual_evidence: Mapped[dict] = mapped_column(JSON, nullable=True) # Alternative transformations ranked lower
    recommendation_rationale: Mapped[str] = mapped_column(Text, nullable=True)
    recommendation_trust_score: Mapped[float] = mapped_column(Float, nullable=True)
    
    status: Mapped[str] = mapped_column(String, default="PENDING") # PENDING, ACCEPTED, REJECTED, IMPLEMENTED
    
    actual_outcome: Mapped[str] = mapped_column(Text, nullable=True)
    actual_fitness_delta: Mapped[float] = mapped_column(Float, nullable=True)
    capability_improvement: Mapped[float] = mapped_column(Float, nullable=True)
    risk_delta: Mapped[float] = mapped_column(Float, nullable=True)
    execution_delta: Mapped[float] = mapped_column(Float, nullable=True)
    success_score: Mapped[float] = mapped_column(Float, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    resolution_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)

class TransformationLibrary(Base):
    """
    Tracks the historical effectiveness of specific structural transformations across the enterprise.
    """
    __tablename__ = "evolution_transformations"
    
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    
    transformation_type: Mapped[str] = mapped_column(String, index=True)
    
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    success_rate: Mapped[float] = mapped_column(Float, default=0.0)
    failure_rate: Mapped[float] = mapped_column(Float, default=0.0)
    
    average_fitness_improvement: Mapped[float] = mapped_column(Float, default=0.0)
    average_risk_reduction: Mapped[float] = mapped_column(Float, default=0.0)
    average_cost: Mapped[float] = mapped_column(Float, default=0.0)
    
    last_applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
