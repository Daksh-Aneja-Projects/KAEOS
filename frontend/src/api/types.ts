/** KAEOS API — shared response/request types (split out of client.ts). */
// ─── Types ───

// Shared domain analytics/workflow layer (all 7 domains return these shapes).
export interface DomainKPI { key: string; label: string; value: number | null; format: 'currency' | 'number' | 'percent' | 'hours'; }
export interface DomainChart { key: string; title: string; type: 'bar' | 'funnel' | 'donut'; items: { label: string; value: number }[]; }
export interface DomainInsight { severity: 'info' | 'warning' | 'critical'; message: string; }
export interface DomainAnalytics { domain: string; kpis: DomainKPI[]; charts: DomainChart[]; insights: DomainInsight[]; }
export interface WorkflowSpec { domain: string; entity_type: string; status_attr: string; states: string[]; transitions: Record<string, string[]>; }
export interface WorkflowEvent { id: string; domain: string; entity_type: string; entity_id: string; from_state: string; to_state: string; actor: string | null; actor_role: string | null; note: string | null; at: string; }
export interface TransitionResult { entity_type: string; entity_id: string; from_state: string; to_state: string; allowed_next: string[]; at: string; note: string | null; }
export interface OrgPulseDomain { domain: string; health: number | null; kpis: DomainKPI[]; critical_count?: number; warning_count?: number; sla_breaches?: number; error?: boolean; }
export interface SLABreach { domain: string; entity_type: string; entity_id: string; title: string; state: string; sla_hours: number; age_hours: number; over_by_hours: number; }
export interface BulkTransitionResult { entity_type: string; to_state: string; requested: number; succeeded: number; failed: number; results: { id: string; ok: boolean; [k: string]: any }[]; }
export interface MyWorkItem { domain: string; entity_type: string; entity_id: string; assignee: string; assigned_by: string | null; note: string | null; title: string | null; state: string | null; at: string; }
export interface EntityComment { id: string; author: string; body: string; mentions: string[]; at: string; }
export interface AppNotification { id: string; type: string; severity: string; title: string; description: string | null; source_type: string | null; source_id: string | null; is_read: boolean; requires_action: boolean; action_taken: boolean; at: string | null; }
export interface AutomationRule { id: string; name: string; is_active: boolean; entity_type: string; trigger_state: string; dwell_hours: number; action_type: 'transition' | 'assign' | 'escalate'; action_to_state: string | null; action_assignee: string | null; times_fired: number; last_fired_at: string | null; }
export interface SavedSegment { id: string; domain: string; name: string; entity_type: string | null; definition: Record<string, any>; created_by?: string | null; }
export interface OrgPulse { org_health: number | null; domains: OrgPulseDomain[]; insights: (DomainInsight & { domain: string })[]; }

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

/** "Recently harvested" strip: who answered, and what was asked. */
export interface AnsweredQuestionSummary {
  id: string;
  employee_name: string;
  question_text: string;
}

export interface ElicitationDashboard {
  pending_questions: QuestionItem[];
  recent_answers: AnsweredQuestionSummary[];
  contributors: ContributorItem[];
  stats: Record<string, number>;
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

export interface ProvenanceEntry {
  id: string;
  /** Present on the global ledger (the row is the full model dict). */
  rule_id?: string | null;
  event_type: string;
  timestamp: string;
  actor_role: string;
  confidence_at: number;
  reasoning: string;
  chain_hash: string;
  rule_statement?: string;
}

export interface Signal {
  id: string;
  source_type: string;
  source_entity: string;
  signal_type: string;
  domain: string;
  clean_payload: string;
  authority_score: number;
  novelty_score: number;
  pii_present: boolean;
  created_at: string;
}

export interface CandidateRule {
  id: string;
  statement: string;
  trigger_json: any;
  action_json: any;
  domain: string;
  confidence_basis: string;
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

export interface GraphData {
  nodes: { id: string; label: string; group: string; department?: string; confidence?: number; domain?: string }[];
  edges: { source: string; target: string; label: string }[];
}

export interface ConnectorItem {
  id: string;
  name: string;
  category: string;
  connector_type: string;
  status: string;
  icon: string;
  description: string;
  auth_method: string;
  sync_frequency: string;
  last_sync_at: string | null;
  events_ingested: number;
  signals_extracted: number;
  error_count: number;
  avg_latency_ms: number;
  pii_scrub_enabled: boolean;
  pii_entities_found: number;
  connected_at: string | null;
  live_integration?: { provider: string; last_test_ok: boolean | null } | null;
}

export interface ConnectorCredentialStatus {
  configured: boolean;
  provider?: string;
  inferred_provider?: string;
  required_config?: string[];
  config?: Record<string, unknown>;
  secret_keys?: string[];
  last_test_ok?: boolean | null;
  last_test_detail?: string | null;
  last_tested_at?: string | null;
}

export interface ConnectorCredentialsBody {
  provider?: string;
  config: Record<string, unknown>;
  secrets: Record<string, string>;
}

export interface ConnectorsResponse {
  connectors: ConnectorItem[];
  stats: {
    total: number;
    connected: number;
    available: number;
    total_events_ingested: number;
    total_signals_extracted: number;
  };
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

// ─── L9 Configurations ───
export interface ModelCapabilityProfile {
  json_compliance?: number;
  reasoning_depth?: number;
  instruction_following?: number;
  tier_ceiling?: number;
  latency_ms?: number;
  probed_at?: string;
  usable?: boolean;
  recommendation?: string;
  errors?: string[];
}

/** Server response - never carries api_key (write-only, encrypted at rest). */
export interface LLMConfigItem {
  id: string;
  layer: string;
  model_name: string;
  provider: string;
  api_base?: string | null;
  key_configured?: boolean;
  capability_profile?: ModelCapabilityProfile;
}

/** Write shape - api_key is sent, never read back. */
export interface LLMConfigInput {
  layer: string;
  model_name: string;
  provider: string;
  api_key?: string | null;
  api_base?: string | null;
}

/** Read shape - the API never returns the key, only whether one is set. */
export interface MCPToolItem {
  id: string;
  tool_id: string;
  is_active: boolean;
  rate_limit_per_hour: number;
  key_configured?: boolean;
}

/** Write shape - api_key is sent, never read back. Blank keeps the stored key. */
export interface MCPToolInput {
  tool_id: string;
  is_active: boolean;
  rate_limit_per_hour: number;
  api_key?: string | null;
}

export interface OntologyConfigItem {
  id?: string;
  department: string;
  default_half_life_days: number;
}

export interface FederatedConfigItem {
  id?: string;
  department: string;
  opt_in: boolean;
}

export interface PendingHITLItem {
  id: string;
  skill_id_name: string;
  status: string;
  route_type?: string;
  task_intent: string;
  started_at: string;
  reasoning_chain: any[];
}

// ─── HR / Workforce Types ───
export interface HREmployee {
  id: string;
  first_name: string;
  last_name: string;
  email?: string;
  status: string;
  job_title?: string;
  location?: string;
  hire_date?: string;
}

export interface HRRequisition {
  id: string;
  title: string;
  department?: string;
  status: string;
  headcount?: number;
  target_salary_min?: number;
  target_salary_max?: number;
}

export interface HRCandidate {
  id: string;
  name: string;
  email?: string;
  stage: string;
  ai_score: number | null;
  ai_summary?: string | null;
  ai_red_flags?: string[];
  requisition_id?: string;
}

export interface HRTimeOffRequest {
  id: string;
  employee_id: string;
  status: string;
  leave_type: string;
  start_date?: string;
  end_date?: string;
  hours_requested?: number;
}

export interface HRPerformanceReview {
  id: string;
  employee_id: string;
  status: string;
  manager_rating: number | null;
  self_rating?: number | null;
  cycle_id?: string;
}

// ─── AI Foundry (v2, Phase 2) types ───
export interface FoundryStats {
  tenant_id: string;
  total_examples: number;
  trainable_examples: number;
  human_verified_examples: number;
  by_label: Record<string, number>;
  by_domain: Record<string, number>;
  by_source: Record<string, number>;
}
export interface FoundryBuildResult {
  tenant_id: string;
  created: number;
  by_label: Record<string, number>;
  skipped: number;
}
export interface FoundryFeedbackInput {
  execution_id?: string;
  corrected_answer?: string;
  rating?: number;
  instruction?: string;
  context?: Record<string, any>;
}
export interface FoundryExample {
  instruction: string;
  context: Record<string, any>;
  output: string;
  reasoning: any[];
  label: string;
  quality: number;
  domain: string;
}

// ─── Notification channels (notifications.py) types ───
export type NotificationKind = 'smtp' | 'slack' | 'webhook';
export interface NotificationChannel {
  id: string;
  name: string;
  kind: NotificationKind;
  config: Record<string, any>; // secrets come back masked (e.g. "***" / "http://1...")
  events: string[]; // empty array = subscribed to all events
  enabled: boolean;
  created_at: string;
}
export interface NotificationDelivery {
  id: string;
  channel_id: string;
  event: string;
  subject: string;
  status: string; // SENT | FAILED
  error: string | null;
  created_at: string;
}

// ─── API Functions ───

// --- Billing / entitlements (billing.py) types ---
export interface BillingUsageRating {
  tenant_id: string;
  period_start: string;
  plan: string;
  metered_executions: number;
  included_allowance: number;
  overage_units: number;
}
export interface BillingPlanCatalogEntry {
  features: string[];
  allowance: number;
}
export interface BillingEntitlements {
  tenant_id: string;
  plan: string;
  /** false on self-hosted installs: every feature is granted and nothing is purchasable. */
  managed_cloud: boolean;
  features: Record<string, boolean>;
  usage: BillingUsageRating;
  /** Full plan catalog for upgrade UIs, keyed by tier. */
  plans: Record<string, BillingPlanCatalogEntry>;
  seats: number | null;
}
export interface SkillValueBaseline {
  skill_name: string;
  baseline_minutes: number;
  hourly_rate: number;
}
