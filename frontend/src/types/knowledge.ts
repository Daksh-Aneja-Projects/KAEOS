/**
 * KAEOS - Knowledge Types
 * Response DTOs for rules, skills, executions, topology
 */

export interface RuleItem {
  id: string;
  statement: string;
  domain: string;
  confidence_scalar: number;
  confidence_tier: string;
  confidence_vector: Record<string, number>;
  is_executable: boolean;
  compliance_tags: string[];
  half_life_days: number;
  created_at: string;
  validated_at: string | null;
}

export interface RuleListResponse {
  total: number;
  rules: RuleItem[];
}

export interface SkillItem {
  id: string;
  skill_id: string;
  department: string;
  domain: string;
  version: string;
  status: string;
  confidence: number;
  confidence_tier: string;
  confidence_vector: Record<string, number>;
  execution_count: number;
  success_rate: number;
  half_life_days: number;
  mcp_tool_bindings: string[];
  compliance_tags: string[];
  triggers: unknown[];
  steps: unknown[];
  exceptions: unknown[];
  guardrails: Record<string, unknown>;
}

export interface SkillRegistryResponse {
  total: number;
  total_executions: number;
  avg_success_rate: number;
  skills: SkillItem[];
}

export interface ExecutionItem {
  id: string;
  status: string;
  route_type: string;
  task_intent: string;
  duration_ms: number;
  hitl_required: boolean;
  outcome_type: string;
  confidence_delta: number;
  started_at: string;
  reasoning_chain: { step: number; action: string; status: string }[];
}

export interface GraphData {
  nodes: { id: string; label: string; group: string; department?: string; confidence?: number; domain?: string }[];
  edges: { source: string; target: string; label: string }[];
}

export interface QuestionItem {
  id: string;
  employee_id: string;
  employee_name: string;
  department: string;
  question_text: string;
  question_type: string;
  context_ref: string;
  delivery_channel: string;
  priority: string;
  status: string;
  specificity: number;
  groundedness: number;
  answerability: number;
  created_at: string;
  answered_at: string | null;
}

export interface ContributorItem {
  employee_id: string;
  display_name: string;
  department: string;
  role: string;
  total_contributions: number;
  confirmed_contributions: number;
  reputation_score: number;
  response_rate: number;
  badge: string | null;
}

export interface ElicitationDashboard {
  pending_questions: QuestionItem[];
  recent_answers: QuestionItem[];
  contributors: ContributorItem[];
  stats: Record<string, number>;
}
