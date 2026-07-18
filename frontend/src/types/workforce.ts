/**
 * KAEOS - Workforce Types
 * Type definitions for the Enterprise Workforce Operating System layer.
 * Maps to backend workforce/models/core.py
 */

export type DepartmentStatus = 'DRAFT' | 'DEPLOYING' | 'ACTIVE' | 'PAUSED' | 'DEGRADED' | 'ARCHIVED';
export type CapabilityStatus = 'PLANNED' | 'DEPLOYING' | 'ACTIVE' | 'DISABLED' | 'DEGRADED';
export type DeploymentStatusType = 'INIT' | 'PACK_SELECTED' | 'SYSTEMS_CONNECTING' | 'INTEGRATIONS_MAPPING' | 'WORKFORCE_GENERATING' | 'AGENTS_DEPLOYING' | 'KNOWLEDGE_SEEDING' | 'RUNTIME_STARTING' | 'ACTIVE' | 'FAILED' | 'ROLLED_BACK';

export interface WfDepartment {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  icon: string;
  status: DepartmentStatus;
  domain_pack_id: string | null;
  employee_count: number;
  agent_count: number;
  capability_count: number;
  process_count: number;
  health_score: number;
  automation_coverage: number;
  tasks_completed_total: number;
  hours_saved_total: number;
  connected_systems: string[];
  compliance_frameworks: string[];
  deployed_at: string | null;
  created_at: string | null;
}

export interface WfCapability {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  icon: string;
  status: CapabilityStatus;
  automation_pct: number;
  tasks_completed: number;
  active_agents: number;
  processes?: WfProcess[];
}

export interface WfProcess {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  department_id: string;
  capability_id: string;
  status: string;
  trigger_type: string;
  automation_pct: number;
  execution_count: number;
  avg_duration_ms: number;
  success_rate: number;
  sla_hours: number | null;
  last_executed_at: string | null;
}

export interface WfAgent {
  id: string;
  agent_name: string;
  agent_type: string;
  role_in_department: string | null;
  persona?: string | null;
  status: string;
  health_score: number;
  tasks_handled: number;
  skills?: string[];
  compliance_tags?: string[];
  last_active_at: string | null;
}

export interface WfDeployment {
  id: string;
  department_id: string | null;
  domain_pack_id: string | null;
  domain_pack_slug: string | null;
  status: DeploymentStatusType;
  current_step: string;
  progress_pct: number;
  selected_capabilities: string[];
  connected_systems: string[];
  employee_count: number;
  deployment_steps?: { step: string; status: string; started_at: string; completed_at?: string; details?: Record<string, any> }[];
  agents_created: string[];
  blueprints_created?: string[];
  capabilities_activated?: string[];
  processes_created?: string[];
  error_log: { step: string; error: string; timestamp: string; recoverable: boolean }[];
  started_at: string | null;
  completed_at: string | null;
}

export interface WorkforceOverview {
  departments_active: number;
  agents_active: number;
  processes_active: number;
  capabilities_active: number;
  total_deployments: number;
  tasks_completed: number;
  hours_saved: number;
  avg_health_score: number;
  avg_automation_coverage: number;
}

export interface WorkforceAnalytics {
  departments_active: number;
  agents_active: number;
  total_tasks_completed: number;
  total_hours_saved: number;
  total_cost_saved: number;
  automation_coverage_pct: number;
  agent_utilization_pct: number;
  human_escalation_rate_pct: number;
  avg_health_score: number;
  avg_agent_health: number;
  departments: {
    id: string;
    name: string;
    slug: string;
    icon: string;
    tasks_completed: number;
    hours_saved: number;
    automation_coverage: number;
    health_score: number;
    agent_count: number;
  }[];
}

export interface ConnectorHealth {
  connector_id: string;
  connector_name: string;
  status: string;
  records_per_hour: number;
  error_rate_pct: number;
  freshness_pct: number;
  events_ingested: number;
  error_count: number;
  last_sync_at: string | null;
  entity_freshness: {
    entity_type: string;
    record_count: number;
    freshness_pct: number;
  }[];
}

export interface ConnectorFeedEvent {
  id: string;
  signal_type: string;
  source_type: string;
  source_entity: string;
  domain: string;
  authority_score: number;
  pii_present: boolean;
  created_at: string | null;
  summary: string | null;
}

export interface ConnectorFeed {
  connector_id: string;
  connector_name: string;
  total: number;
  events: ConnectorFeedEvent[];
}
