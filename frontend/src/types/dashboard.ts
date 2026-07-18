/**
 * KAEOS - Dashboard Types
 * Response DTOs for /dashboard/* endpoints
 */

export interface DepartmentCoverage {
  department: string;
  coverage: number;
  rule_count: number;
  trend: string;
}

export interface ConfidenceDistribution {
  speculative: number;
  inferred: number;
  validated_peer: number;
  validated_dh: number;
  verified: number;
}

export interface DecayAlert {
  rule_id: string;
  statement: string;
  domain: string;
  current_confidence: number;
  days_since_validation: number;
  half_life_days: number;
  urgency: string;
}

export interface AgentMetrics {
  total_executions_7d: number;
  success_rate: number;
  rag_fallback_rate: number;
  human_overrides: number;
  avg_duration_ms: number;
  skills_used: number;
}

export interface ElicitationMetrics {
  questions_sent_7d: number;
  response_rate: number;
  entries_created: number;
  avg_time_to_answer_hours: number;
  top_contributors: { name: string; score: number; contributions: number }[];
}

export interface KBHealth {
  overall_score: number;
  score_trend: string;
  total_rules: number;
  total_skills: number;
  total_executions: number;
  coverage: DepartmentCoverage[];
  confidence_distribution: ConfidenceDistribution;
  decay_alerts: DecayAlert[];
  agent_metrics: AgentMetrics;
  elicitation_metrics: ElicitationMetrics;
  freshness: { within_half_life: number; decaying: number; expired: number };
}

export interface ComplianceFramework {
  framework: string;
  coverage_pct: number;
  violations: number;
  blocker_count: number;
  last_audit: string | null;
  status: string;
}

export interface ComplianceDashboard {
  frameworks: ComplianceFramework[];
  total_tagged_rules: number;
  untagged_rules: number;
}

export interface CockpitData {
  pioneer_alerts: {
    type: string;
    title: string;
    severity: string;
    source: string;
    time: string;
  }[];
  debate_queue: {
    id: string;
    action: string;
    confidence: number;
    status: string;
    created_at: string | null;
  }[];
  org_readiness: {
    bu: string;
    score: number;
    rule_count: number;
    status: string;
  }[];
  cost: any;
}

export interface OODAEvent {
  id: string;
  phase: 'OBSERVE' | 'ORIENT' | 'DECIDE' | 'ACT';
  status: 'active' | 'complete' | 'blocked' | 'pending';
  title: string;
  detail: string;
  confidence?: number;
  gate?: string;
  timestamp: string;
}

export interface OODAEventsResponse {
  events: OODAEvent[];
}
