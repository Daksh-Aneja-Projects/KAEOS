/**
 * KAEOS - Brain Overview Types
 * Response DTOs for /brain/* and /departments/* endpoints
 */

export interface BrainOverview {
  enterprise_iq: number;
  knowledge_coverage: number;
  avg_confidence: number;
  freshness_ratio: number;
  success_rate: number;
  departments: number;
  processes: number;
  workforces: number;
  total_rules: number;
  executable_rules: number;
  total_skills: number;
  total_executions: number;
  total_signals: number;
}

export interface Department {
  id: string;
  name: string;
  rule_count: number;
  executable_rules: number;
  skill_count: number;
  workflow_count: number;
  avg_confidence: number;
  avg_success_rate: number;
  coverage: number;
  status: string;
}

export interface DepartmentListResponse {
  total: number;
  departments: Department[];
}

export interface DepartmentCapability {
  id: string;
  skill_id: string;
  name: string;
  domain: string;
  version: string;
  status: string;
  confidence: number;
  confidence_tier: string | null;
  execution_count: number;
  success_rate: number;
  mcp_tool_bindings: string[];
  compliance_tags: string[];
}

export interface DepartmentCapabilitiesResponse {
  department: string;
  department_name: string;
  total_capabilities: number;
  total_executions: number;
  avg_confidence: number;
  avg_success_rate: number;
  capabilities: DepartmentCapability[];
}

export interface Process {
  id: string;
  name: string;
  department: string;
  status: string;
  steps: any[];
  created_at: string | null;
}

export interface ProcessListResponse {
  total: number;
  processes: Process[];
}

export interface WorkforceAgent {
  id: string;
  agent_name: string;
  agent_type: string | null;
  status: string | null;
  department: string | null;
  blueprint_id: string;
  execution_count: number;
  success_count: number;
  success_rate: number;
  health_status: string;
  last_executed_at: string | null;
  created_at: string | null;
}

export interface WorkforceListResponse {
  total: number;
  workforces: WorkforceAgent[];
}
