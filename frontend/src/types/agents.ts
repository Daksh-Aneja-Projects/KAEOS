/**
 * KAEOS - Agent Factory Types
 * Response DTOs for blueprints, deployed agents, debates, activity feed, fairness
 */

export interface Blueprint {
  id: string;
  name: string;
  status: string;
  original_prompt: string;
  dag_nodes: any[];
  created_by: string;
  created_at: string;
}

export interface DeployedAgent {
  id: string;
  agent_name: string;
  agent_type: string | null;
  status: string | null;
  blueprint_id: string;
  compiled_skill_id: string;
  execution_count: number;
  success_count: number;
  health_status: string;
  last_executed_at: string | null;
  created_at: string | null;
}

export interface DebateTranscript {
  id: string;
  execution_id: string;
  skill_id: string;
  decision: string;
  confidence: number;
  arbitrator_decision: any;
  escalated: boolean;
  duration_ms: number;
  created_at: string | null;
}

export interface ActivityFeedEvent {
  id: string;
  title: string;
  event_type: string;
  severity: string;
  created_at: string;
  is_read: boolean;
}

export interface FairnessAuditEntry {
  id: string;
  fairness_score: number;
  passed: boolean;
  threshold: number;
  flagged_attributes: string[];
  rationale: string;
  action_description: string;
  entity_type: string;
  was_overridden: boolean;
  override_by: string | null;
  created_at: string | null;
}

export interface PendingHITLItem {
  id: string;
  skill_id_name: string;
  status: string;
  task_intent: string;
  context: any;
  started_at: string;
  reasoning_chain: any[];
}
