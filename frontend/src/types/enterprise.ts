/**
 * KAEOS - Enterprise Types
 * Response DTOs for security, provenance, conflicts, marketplace, benchmarks
 */

export interface SecurityLog {
  id: string;
  event_type: string;
  actor_hash: string;
  actor_role: string;
  resource_type: string;
  resource_id: string | null;
  action: string;
  result: string;
  ip_address: string;
  details: Record<string, any>;
  timestamp: string;
}

export interface ProvenanceEntry {
  id: string;
  event_type: string;
  timestamp: string;
  actor_role: string;
  confidence_at: number;
  reasoning: string;
  chain_hash: string;
  rule_statement?: string;
}

export interface ConflictItem {
  id: string;
  conflict_type: string;
  severity: string;
  status: string;
  assigned_to: string | null;
  deadline: string | null;
  detected_at: string;
  resolved_at: string | null;
  resolution_type: string | null;
  resolution_note: string | null;
  rule_a: { id: string; statement: string; domain: string; confidence: number; sources: number; validated_at: string | null } | null;
  rule_b: { id: string; statement: string; domain: string; confidence: number; sources: number; validated_at: string | null } | null;
}

export interface MarketplaceItem {
  id: string;
  name: string;
  category: string;
  description: string;
  author: string;
  version: string;
  rating: number;
  installs: number;
  rules_count: number;
  skills_count: number;
  tags: string[];
  compliance_frameworks: string[];
  certified: boolean;
  preview_data: Record<string, any>;
}

export interface BenchmarkData {
  local_org: {
    kb_coverage_pct: number;
    agent_autonomy_pct: number;
    time_to_onboard_days: number;
    active_skills: number;
  };
  industry_median: {
    kb_coverage_pct: number;
    agent_autonomy_pct: number;
    time_to_onboard_days: number;
    active_skills: number;
  };
  top_quartile: {
    kb_coverage_pct: number;
    agent_autonomy_pct: number;
    time_to_onboard_days: number;
    active_skills: number;
  };
  department_benchmarks: {
    department: string;
    local_coverage: number;
    industry_median: number;
    status: string;
  }[];
}

export interface RedTeamScan {
  skill_id: string;
  department: string;
  status: string;
  vulnerabilities: number;
  scan_count: number;
  last_scan: string;
  scan_types: string[];
  details: {
    scan_type: string;
    status: string;
    vulnerabilities: number;
    details: any[];
    confidence_at_scan: number;
    duration_ms: number;
    scanned_at: string;
  }[];
}
