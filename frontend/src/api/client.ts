/**
 * KAEOS - API Client
 * Typed fetch wrapper for all backend endpoints - ZERO hardcoded data
 */

declare global { interface Window { __kaeos_reloading?: boolean; } }

const API_BASE = import.meta.env.VITE_API_BASE || `http://${window.location.hostname}:8001/api/v1`;

export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const token = localStorage.getItem('kaeos-token');
  const authHeaders: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  if (token) {
    authHeaders['Authorization'] = `Bearer ${token}`;
  }
  // Spread options FIRST, then set the merged headers - otherwise `...options`
  // (when a caller passes its own `headers`, e.g. X-Admin-Secret) would clobber
  // the merged object and drop Content-Type/Authorization, which FastAPI then
  // rejects with a 422 on any JSON body.
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { ...authHeaders, ...options?.headers },
  });
  if (!res.ok) {
    // Session expired or token revoked - drop the stale token so the
    // AuthGuard returns the user to the login page instead of a dead UI.
    if (res.status === 401 && token && !path.startsWith('/auth/login')) {
      localStorage.removeItem('kaeos-token');
      if (!window.__kaeos_reloading) {
        window.__kaeos_reloading = true;
        window.location.reload();
      }
    }
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    // FastAPI validation errors return `detail` as an array of {loc,msg,type};
    // coerce anything non-string to a readable message so the UI never shows
    // "[object Object]".
    let detail = err?.detail;
    if (Array.isArray(detail)) {
      detail = detail.map((d: any) => d?.msg || JSON.stringify(d)).join('; ');
    } else if (detail && typeof detail === 'object') {
      detail = detail.msg || JSON.stringify(detail);
    }
    throw new Error(detail || `API Error ${res.status}`);
  }
  return res.json();
}

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

export interface ElicitationDashboard {
  pending_questions: QuestionItem[];
  recent_answers: QuestionItem[];
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
  context: any;
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

// ─── API Functions ───
export const api = {
  // Auth
  authMe: () => request<any>('/auth/me'),
  authLogin: (credentials: any) => request<any>('/auth/login', { method: 'POST', body: JSON.stringify(credentials) }),
  authUsers: () => request<any>('/auth/users'),
  authCreateUser: (data: any) => request<any>('/auth/users', { method: 'POST', body: JSON.stringify(data) }),
  authUpdateRole: (id: string, role: string) => request<any>(`/auth/users/${id}/role`, { method: 'PUT', body: JSON.stringify({ role }) }),
  authDeleteUser: (id: string) => request<any>(`/auth/users/${id}`, { method: 'DELETE' }),

  // Dashboard
  getHealth: () => request<KBHealth>('/dashboard/health'),
  getCompliance: () => request<ComplianceDashboard>('/dashboard/compliance'),

  // Rules
  getRules: (params?: { domain?: string; confidence_tier?: string }) => {
    const qs = new URLSearchParams();
    if (params?.domain) qs.set('domain', params.domain);
    if (params?.confidence_tier) qs.set('confidence_tier', params.confidence_tier);
    return request<RuleListResponse>(`/rules?${qs}`);
  },
  getRule: (id: string) => request<RuleItem>(`/rules/${id}`),
  getProvenance: (id: string) => request<ProvenanceEntry[]>(`/rules/${id}/provenance`),

  // Skills
  getSkills: () => request<SkillRegistryResponse>('/skills'),
  getSkill: (id: string) => request<SkillItem>(`/skills/${id}`),
  getExecutions: (skillId: string) => request<ExecutionItem[]>(`/skills/${skillId}/executions`),
  executeSkill: (skillId: string, intent: string) =>
    request(`/skills/${skillId}/execute`, {
      method: 'POST',
      body: JSON.stringify({ intent, context: {} }),
    }),

  // Elicitation
  getElicitation: () => request<ElicitationDashboard>('/elicitation/dashboard'),
  submitAnswer: (questionId: string, answer: string) =>
    request('/elicitation/answer', {
      method: 'POST',
      body: JSON.stringify({ question_id: questionId, answer_text: answer }),
    }),

  // Extraction (L2)
  getSignals: () => request<{ signals: Signal[] }>('/extraction/signals'),
  getCandidates: () => request<{ candidates: CandidateRule[] }>('/extraction/candidates'),
  detectConflict: (candidate: CandidateRule) => request('/extraction/detect-conflict', {
    method: 'POST',
    body: JSON.stringify(candidate),
  }),

  // Provenance (L11)
  getGlobalLedger: () => request<{ ledger: ProvenanceEntry[] }>('/provenance/global/ledger'),

  // RedTeam (L12)
  getRecentScans: () => request<{ scans: RedTeamScan[]; summary: any }>('/redteam/scans/recent'),
  runScan: (skillId: string) => request(`/redteam/scan/${skillId}`, { method: 'POST' }),

  // Benchmark (L14)
  getBenchmark: () => request<BenchmarkData>('/benchmark/network'),

  // Topology (L4)
  getGraph: () => request<GraphData>('/topology/graph'),

  // Connectors (L0)
  getConnectors: () => request<ConnectorsResponse>('/connectors'),
  /** Catalog of every live integration KAEOS supports, grouped by domain. */
  getConnectorProviders: () => request<{
    total: number;
    providers: Array<{
      id: string; domain: string; entity: string;
      authority: number; handles_pii: boolean; required_config: string[];
    }>;
    by_domain: Record<string, string[]>;
  }>('/connectors/providers'),
  connectConnector: (id: string) => request(`/connectors/${id}/connect`, { method: 'POST' }),
  disconnectConnector: (id: string) => request(`/connectors/${id}/disconnect`, { method: 'POST' }),
  getConnectorCredentialStatus: (id: string) =>
    request<ConnectorCredentialStatus>(`/connectors/${id}/credentials`),
  storeConnectorCredentials: (id: string, body: ConnectorCredentialsBody) =>
    request(`/connectors/${id}/credentials`, { method: 'PUT', body: JSON.stringify(body) }),
  deleteConnectorCredentials: (id: string) =>
    request(`/connectors/${id}/credentials`, { method: 'DELETE' }),
  testConnector: (id: string) =>
    request<{ ok: boolean; detail: string; provider: string }>(`/connectors/${id}/test`, { method: 'POST' }),
  syncConnector: (id: string) =>
    request<{ status: string; mode: string; events_synced: number }>(`/connectors/${id}/sync`, { method: 'POST' }),

  // Conflicts (L16)
  getConflicts: () => request<{ conflicts: ConflictItem[]; open_count: number; total: number }>('/conflicts'),
  resolveConflict: (id: string, resolution_type: string, note?: string) =>
    request(`/conflicts/${id}/resolve`, {
      method: 'POST',
      body: JSON.stringify({ resolution_type, resolution_note: note }),
    }),

  // Marketplace (L19)
  getMarketplace: () => request<{ templates: MarketplaceItem[]; total: number; categories: string[] }>('/marketplace'),
  createMarketplaceTemplate: (data: { name: string; category: string; description: string; author: string; tags: string[] }) =>
    request<{ status: string; id: string }>('/marketplace', {
      method: 'POST',
      body: JSON.stringify(data)
    }),

  // Security (L17)
  getSecurityLog: () => request<{ logs: SecurityLog[]; stats: { total_events: number; blocked: number; escalated: number; allowed: number } }>('/security/audit-log'),

  // --- New L9 Gaps ---
  // HITL
  // Single HITL queue: the DB is the source of truth for ALL pending
  // approvals, including Gate-3 pipeline pauses (route_type GATED_AGENT).
  getPendingHITL: () => request<PendingHITLItem[]>('/skills/hitl/pending'),
  approveHITL: (execId: string) => request(`/skills/hitl/${execId}/approve`, { method: 'POST' }),
  rejectHITL: (execId: string) => request(`/skills/hitl/${execId}/reject`, { method: 'POST' }),

  // LLM Routing / BYOK
  // Autonomy Dial — per-domain risk appetite (the confidence a domain must clear to run without a human)
  getAutonomy: () => request<{ domain: string; min_confidence: number; is_default: boolean }[]>('/config/autonomy'),
  setAutonomy: (domain: string, min_confidence: number) =>
    request<any>(`/config/autonomy/${domain}`, { method: 'PUT', body: JSON.stringify({ min_confidence }) }),

  getLLMConfig: () => request<LLMConfigItem[]>('/config/llm-routing'),
  updateLLMConfig: (config: LLMConfigInput) => request<LLMConfigItem>('/config/llm-routing', {
    method: 'POST',
    body: JSON.stringify(config)
  }),
  deleteLLMConfig: (layer: string) => request<any>(`/config/llm-routing/${layer}`, { method: 'DELETE' }),
  /** Self-calibrate the tenant's model; returns the capability profile that caps autonomy. */
  probeLLMModel: (layer: string) => request<{ layer: string; model_name: string; profile: ModelCapabilityProfile }>(
    `/config/llm-routing/${layer}/probe`, { method: 'POST' }
  ),

  // MCP Tools
  getMCPTools: () => request<MCPToolItem[]>('/config/mcp-tools'),
  updateMCPTool: (config: MCPToolInput) => request<MCPToolItem>('/config/mcp-tools', {
    method: 'POST',
    body: JSON.stringify(config)
  }),

  // Ontology Config
  getOntologyConfig: () => request<OntologyConfigItem[]>('/config/ontology'),
  updateOntologyConfig: (config: OntologyConfigItem) => request<OntologyConfigItem>('/config/ontology', {
    method: 'POST',
    body: JSON.stringify(config)
  }),

  // Federated Settings
  getFederatedConfig: () => request<FederatedConfigItem[]>('/config/federated'),
  updateFederatedConfig: (config: FederatedConfigItem) => request<FederatedConfigItem>('/config/federated', {
    method: 'POST',
    body: JSON.stringify(config)
  }),

  // ─── Enterprise Platform APIs ───
  getSystemStats: () => request<any>('/system/stats'),
  getReadiness: () => request<any>('/ready'),
  globalSearch: (q: string) => request<any>(`/search?q=${encodeURIComponent(q)}`),
  exportRules: (format: string = 'json') => request<any>(`/export/rules?format=${format}`),
  exportSkills: () => request<any>('/export/skills'),
  importRules: (rules: any[]) => request<any>('/import/rules', { method: 'POST', body: JSON.stringify({ rules }) }),
  getRuleVersions: (ruleId: string) => request<any>(`/rules/${ruleId}/versions`),
  cloneRule: (ruleId: string, newDomain?: string) => request<any>(`/rules/${ruleId}/clone`, {
    method: 'POST', body: JSON.stringify({ new_domain: newDomain })
  }),
  simulate: (ruleId: string, scenario: string, params?: any) => request<any>('/simulate', {
    method: 'POST', body: JSON.stringify({ rule_id: ruleId, scenario, params: params || {} })
  }),
  getHealthReport: () => request<any>('/reports/health'),
  getComplianceReport: () => request<any>('/reports/compliance'),
  getTenantStats: () => request<any>('/tenants/stats'),
  getWebhooks: () => request<any>('/webhooks'),
  createWebhook: (name: string, endpoint: string, events: string[]) => request<any>('/webhooks', {
    method: 'POST', body: JSON.stringify({ name, endpoint, events })
  }),
  deleteWebhook: (id: string) => request<any>(`/webhooks/${id}`, { method: 'DELETE' }),
  getEventLog: (limit: number = 50) => request<any>(`/events/log?limit=${limit}`),

  // ─── AEOS Agent Factory APIs ───
  // Blueprints
  createBlueprint: (prompt: string, createdBy?: string) => request<any>('/agents/blueprint', {
    method: 'POST', body: JSON.stringify({ prompt, created_by: createdBy })
  }),
  listBlueprints: () => request<any>('/agents/blueprints'),
  getBlueprint: (id: string) => request<any>(`/agents/blueprint/${id}`),
  refineBlueprint: (id: string, edits: any) => request<any>(`/agents/blueprint/${id}`, {
    method: 'PUT', body: JSON.stringify(edits)
  }),
  approveBlueprint: (id: string, approvedBy?: string) => request<any>(`/agents/blueprint/${id}/approve`, {
    method: 'POST', body: JSON.stringify({ approved_by: approvedBy })
  }),
  compileBlueprint: (id: string) => request<any>(`/agents/blueprint/${id}/compile`, { method: 'POST' }),
  deployBlueprint: (id: string, triggerConfig?: any) => request<any>(`/agents/blueprint/${id}/deploy`, {
    method: 'POST', body: JSON.stringify({ trigger_config: triggerConfig })
  }),

  // Deployed Agents
  listDeployedAgents: () => request<any>('/agents/deployed'),
  getDeployedAgent: (id: string) => request<any>(`/agents/deployed/${id}`),
  stopAgent: (id: string) => request<any>(`/agents/deployed/${id}/stop`, { method: 'POST' }),
  pauseAgent: (id: string) => request<any>(`/agents/deployed/${id}/pause`, { method: 'POST' }),

  // Activity Feed
  getActivityFeed: (limit: number = 50, unreadOnly: boolean = false) =>
    request<any>(`/agents/activity-feed?limit=${limit}&unread_only=${unreadOnly}`),
  markFeedRead: (eventIds: string[]) => request<any>('/agents/activity-feed/mark-read', {
    method: 'POST', body: JSON.stringify({ event_ids: eventIds })
  }),
  getActionRequired: () => request<any>('/agents/activity-feed/action-required'),

  // Debate Engine
  getDebateTranscript: (executionId: string) => request<any>(`/agents/debates/${executionId}`),
  getRecentDebates: () => request<any>('/agents/debates/recent'),

  // Fairness (AEOS P3)
  getFairnessLog: (limit: number = 50) => request<any>(`/fairness/audit-log?limit=${limit}`),
  overrideFairness: (logId: string, overrideBy: string, justification: string) =>
    request<any>(`/fairness/override/${logId}`, {
      method: 'POST', body: JSON.stringify({ override_by: overrideBy, justification })
    }),

  // Calendar (AEOS P4)
  getCalendarEvents: () => request<any>('/calendar/events'),
  createCalendarEvent: (data: any) => request<any>('/calendar/events', {
    method: 'POST', body: JSON.stringify(data)
  }),
  deleteCalendarEvent: (id: string) => request<any>(`/calendar/events/${id}`, { method: 'DELETE' }),
  getTemporalContext: (department?: string) =>
    request<any>(`/calendar/context?department=${department || 'general'}`),

  // ─── AEOS Pioneer Layer APIs ───
  // P1: External Intelligence
  ingestSignal: (data: { signal_type: string; source: string; title: string; content: string; severity?: string }) =>
    request<any>('/intelligence/signals', { method: 'POST', body: JSON.stringify(data) }),
  correlateSignal: (content: string) =>
    request<any>('/intelligence/correlate', { method: 'POST', body: JSON.stringify({ signal_content: content }) }),
  generateProactiveAlert: (data: any) =>
    request<any>('/intelligence/proactive-alert', { method: 'POST', body: JSON.stringify(data) }),

  // P2: Org Intelligence
  scoreChangeReadiness: (department: string, changeDescription: string) =>
    request<any>('/org-intelligence/change-readiness', {
      method: 'POST', body: JSON.stringify({ department, change_description: changeDescription })
    }),
  mapInfluencePath: (targetOutcome: string, department: string) =>
    request<any>('/org-intelligence/influence-path', {
      method: 'POST', body: JSON.stringify({ target_outcome: targetOutcome, department })
    }),
  getSkillsTopology: () => request<any>('/org-intelligence/skills-topology'),

  // Topology
  getTopology: () => request<any>('/topology/graph'),

  // Provenance Ledger
  getProvenanceLedger: () => request<any>('/provenance/global/ledger'),

  // Elicitation
  getElicitationDashboard: () => request<any>('/elicitation/dashboard'),

  // L6: Simulation
  runSimulation: (changeDescription: string, targetDomain: string, riskTolerance?: string) =>
    request<any>('/simulation/what-if', {
      method: 'POST', body: JSON.stringify({
        change_description: changeDescription, target_domain: targetDomain,
        risk_tolerance: riskTolerance || 'MEDIUM'
      })
    }),

  // ─── S1 Infrastructure Layer (KAEOS N1-N4) ───

  // N1: Model Management
  getModelRegistry: () => request<any[]>('/infrastructure/models'),
  registerModel: (data: any) => request<any>('/infrastructure/models', {
    method: 'POST', body: JSON.stringify(data)
  }),
  routeModel: (requestType: string) => request<any>('/infrastructure/models/route', {
    method: 'POST', body: JSON.stringify({ request_type: requestType })
  }),
  estimateTokens: (requestType: string) => request<any>(`/infrastructure/models/estimate?request_type=${requestType}`),
  getPromptTemplates: () => request<any[]>('/infrastructure/prompts'),
  registerPrompt: (data: any) => request<any>('/infrastructure/prompts', {
    method: 'POST', body: JSON.stringify(data)
  }),

  // N2: Cost Governor
  getCostTelemetry: (hours: number = 24) => request<any>(`/infrastructure/cost/telemetry?hours=${hours}`),
  getCostBudgets: () => request<any[]>('/infrastructure/cost/budgets'),
  createCostBudget: (data: any) => request<any>('/infrastructure/cost/budgets', {
    method: 'POST', body: JSON.stringify(data)
  }),
  checkBudget: (estimatedTokens: number) => request<any>('/infrastructure/cost/check', {
    method: 'POST', body: JSON.stringify({ estimated_tokens: estimatedTokens })
  }),

  // N3: Agent Protocol
  getAgentRegistry: () => request<any[]>('/infrastructure/agents/registry'),
  registerAgent: (data: any) => request<any>('/infrastructure/agents/register', {
    method: 'POST', body: JSON.stringify(data)
  }),
  discoverAgent: (capability: string) => request<any>('/infrastructure/agents/discover', {
    method: 'POST', body: JSON.stringify({ capability })
  }),
  sendAgentMessage: (data: any) => request<any>('/infrastructure/agents/message', {
    method: 'POST', body: JSON.stringify(data)
  }),
  getAgentMessages: (correlationId?: string) => request<any[]>(
    `/infrastructure/agents/messages${correlationId ? `?correlation_id=${correlationId}` : ''}`
  ),

  // N4: Onboarding
  // adminSecret (optional): platform-operator secret sent as X-Admin-Secret to
  // provision / read / advance a DIFFERENT tenant than the caller's own. Own
  // tenant needs no secret. It is passed only in the request header, never
  // stored. See app/core/admin.py verify_admin_secret.
  getOnboardingList: (adminSecret?: string) => request<any[]>('/infrastructure/onboarding',
    adminSecret ? { headers: { 'X-Admin-Secret': adminSecret } } : undefined),
  getOnboardingStatus: (tenantId: string, adminSecret?: string) =>
    request<any>(`/infrastructure/onboarding/${tenantId}`,
      adminSecret ? { headers: { 'X-Admin-Secret': adminSecret } } : undefined),
  initiateOnboarding: (data: { tenant_id?: string; tenant_name?: string; industry_vertical?: string }, adminSecret?: string) =>
    request<any>('/infrastructure/onboarding', {
      method: 'POST', body: JSON.stringify(data),
      ...(adminSecret ? { headers: { 'X-Admin-Secret': adminSecret } } : {}),
    }),
  advanceOnboarding: (tenantId: string, metrics?: Record<string, number>, adminSecret?: string) =>
    request<any>(`/infrastructure/onboarding/${tenantId}/advance`, {
      method: 'POST', body: JSON.stringify(metrics ? { metrics } : {}),
      ...(adminSecret ? { headers: { 'X-Admin-Secret': adminSecret } } : {}),
    }),
  /** Bootstrap the FIRST admin login for a freshly-provisioned tenant. Requires
   * the platform admin secret (X-Admin-Secret) - the one cross-tenant primitive
   * the tenant-scoped /auth/users cannot provide. The client then signs in with
   * these credentials and self-serves the rest of onboarding. */
  bootstrapTenantAdmin: (tenantId: string, data: { email: string; display_name: string; password: string }, adminSecret: string) =>
    request<{ id: string; email: string; display_name: string; role: string; tenant_id: string }>(
      `/infrastructure/onboarding/${tenantId}/bootstrap-admin`, {
        method: 'POST', body: JSON.stringify(data),
        headers: { 'X-Admin-Secret': adminSecret },
      }),
  proposeSchemaMappings: (connectorId: string, sourceFields: any[]) => request<any[]>(
    '/infrastructure/schema-mappings/propose', {
      method: 'POST', body: JSON.stringify({ connector_id: connectorId, source_fields: sourceFields })
    }
  ),
  getSchemaMappings: (connectorId?: string) => request<any[]>(
    `/infrastructure/schema-mappings${connectorId ? `?connector_id=${connectorId}` : ''}`
  ),
  confirmSchemaMapping: (mappingId: string, confirmedBy: string) => request<any>(
    `/infrastructure/schema-mappings/${mappingId}/confirm`, {
      method: 'POST', body: JSON.stringify({ confirmed_by: confirmedBy })
    }
  ),

  // ─── HR / Workforce APIs ───
  getHREmployees: () => request<HREmployee[]>(`/hr/employees`),
  getHREmployee: (id: string) => request<HREmployee>(`/hr/employees/${id}`),
  getHRRequisitions: () => request<HRRequisition[]>(`/hr/requisitions`),
  getHRCandidates: () => request<HRCandidate[]>(`/hr/candidates`),
  getHRTimeOffRequests: () => request<HRTimeOffRequest[]>(`/hr/time-off-requests`),
  getHRPerformanceReviews: () => request<HRPerformanceReview[]>(`/hr/performance-reviews`),

  getHRDashboard: () => request<any>('/hr/dashboard'),

  // HR mutations / triggers (tenant derived server-side from auth context)
  createHRRequisition: (data: { title: string; department: string; hiring_manager_id: string; job_description: string; headcount?: number; requirements?: string[]; target_salary_min?: number; target_salary_max?: number }) =>
    request<{ id: string; title: string; status: string }>('/hr/requisitions', { method: 'POST', body: JSON.stringify(data) }),
  addHRCandidate: (data: { requisition_id: string; first_name: string; last_name: string; email: string; phone?: string; resume_path?: string }) =>
    request<{ id: string; stage: string }>('/hr/candidates', { method: 'POST', body: JSON.stringify(data) }),
  screenHRCandidate: (candidateId: string) =>
    request<any>(`/hr/candidates/${candidateId}/screen`, { method: 'POST' }),
  advanceHRCandidate: (candidateId: string, targetStage: string) =>
    request<{ candidate_id: string; stage: string }>(`/hr/candidates/${candidateId}/advance`, {
      method: 'POST', body: JSON.stringify({ target_stage: targetStage }),
    }),
  hrHitlApprove: (executionId: string, reason = '', approver = 'human') =>
    request<any>(`/hr/hitl/${executionId}/approve`, { method: 'POST', body: JSON.stringify({ reason, approver }) }),
  hrHitlReject: (executionId: string, reason = '', approver = 'human') =>
    request<any>(`/hr/hitl/${executionId}/reject`, { method: 'POST', body: JSON.stringify({ reason, approver }) }),

  // ─── Enterprise Brain APIs (Directive Compliance) ───

  // Brain Overview - the single source of truth
  getBrainOverview: () => request<any>('/brain/overview'),

  // Departments - dynamic from DB, never hardcoded
  getDepartments: () => request<any>('/departments'),
  getDepartmentCapabilities: (deptId: string) => request<any>(`/departments/${deptId}/capabilities`),

  // Processes - maps to Workflow model
  getProcesses: () => request<any>('/processes'),

  // Workforces - maps to DeployedAgent model
  getWorkforces: () => request<any>('/workforces'),

  // Knowledge Graph - alias for /topology/graph
  getKnowledgeGraph: () => request<any>('/topology/knowledge/graph'),

  // OODA Cognitive Loop - the Brain's heartbeat
  getOODAEvents: () => request<any>('/dashboard/ooda-events'),

  // Executive Cockpit - aggregated C-suite intelligence
  getCockpit: () => request<any>('/dashboard/cockpit'),

  // ─── Workforce Layer APIs (EWOS) ───
  // Departments
  getWorkforceDepartments: (status?: string) => request<any>(`/workforce/departments${status ? `?status=${status}` : ''}`),
  getWorkforceDepartment: (id: string) => request<any>(`/workforce/departments/${id}`),
  getDepartmentCapabilities_wf: (id: string) => request<any>(`/workforce/departments/${id}/capabilities`),
  getDepartmentAgents_wf: (id: string) => request<any>(`/workforce/departments/${id}/agents`),
  getWorkforceOverview: () => request<any>('/workforce/overview'),
  // The learning curve: autonomy over time, and the skills that earned it.
  getAutonomyTrend: (days = 30) => request<any>(`/workforce/autonomy-trend?days=${days}`),
  getGraduations: () => request<any>('/workforce/graduations'),

  // Domain Packs (Marketplace)
  getDomainPacks: (category?: string) => request<any>(`/workforce/packs/${category ? `?category=${category}` : ''}`),
  getDomainPack: (id: string) => request<any>(`/workforce/packs/${id}`),
  getDomainPackInstallations: () => request<any>('/workforce/packs/installations'),

  // Deployments
  getWorkforceDeployments: () => request<any>('/workforce/deployments/'),
  getDeployment: (id: string) => request<any>(`/workforce/deployments/${id}`),
  startDeployment: (data: { domain_pack_id: string; domain_pack_slug?: string; tenant_id?: string; selected_capabilities?: string[]; connected_systems?: string[]; employee_count?: number }) =>
    request<any>('/workforce/deployments/start', { method: 'POST', body: JSON.stringify(data) }),
  advanceDeployment: (id: string, stepData?: Record<string, any>) =>
    request<any>(`/workforce/deployments/${id}/advance`, { method: 'POST', body: JSON.stringify({ step_data: stepData || {} }) }),

  // Processes
  getWorkforceProcesses: (departmentId?: string) => request<any>(`/workforce/processes${departmentId ? `?department_id=${departmentId}` : ''}`),
  getWorkforceProcess: (id: string) => request<any>(`/workforce/processes/${id}`),

  // Analytics
  getWorkforceAnalytics: () => request<any>('/workforce/analytics'),

  // Safe-autonomy-rate (north-star) detail: rate + fallout breakdown + per-skill + time-series
  getSafeAutonomy: (days = 30) => request<any>(`/metrics/safe-autonomy?days=${days}`),

  // Outcome Intelligence Loop — record a decision's real-world outcome + read the impact
  getOutcomeImpact: (days = 30) => request<any>(`/outcomes/impact?days=${days}`),
  recordOutcome: (executionId: string, outcome: 'GOOD' | 'BAD' | 'NEUTRAL') =>
    request<any>(`/outcomes/${executionId}`, { method: 'POST', body: JSON.stringify({ outcome }) }),
  getDecisionFeed: () => request<any>('/hitl/decision-feed'),

  // Cross-Domain Missions — goal decomposed into a governed DAG across departments
  listMissions: (limit = 50) => request<any>(`/missions?limit=${limit}`),
  getMission: (id: string) => request<any>(`/missions/${id}`),
  createMission: (goal: string, budget_usd?: number | null) =>
    request<any>('/missions', { method: 'POST', body: JSON.stringify({ goal, budget_usd: budget_usd ?? null }) }),
  advanceMission: (id: string) => request<any>(`/missions/${id}/advance`, { method: 'POST' }),
  resolveMissionHitl: (id: string, seq: number, approved: boolean) =>
    request<any>(`/missions/${id}/steps/${seq}/hitl`, { method: 'POST', body: JSON.stringify({ approved }) }),
  abortMission: (id: string) => request<any>(`/missions/${id}/abort`, { method: 'POST' }),

  // SoR Actuation — the Actions Ledger (what KAEOS DID, reversible) + drift
  getActionsLedger: (limit = 50) => request<any>(`/actuation/ledger?limit=${limit}`),
  getActuationDrift: () => request<any>('/actuation/drift'),
  reverseAction: (actionId: string) =>
    request<any>(`/actuation/${actionId}/reverse`, { method: 'POST' }),

  // ─── Finance Department APIs ───
  getFinanceDashboard: () => request<any>('/finance/dashboard'),
  getFinanceVendors: () => request<any[]>('/finance/vendors'),
  getFinanceVendor: (id: string) => request<any>(`/finance/vendors/${id}`),
  getFinanceInvoices: () => request<any[]>('/finance/invoices'),
  getFinancePayments: () => request<any[]>('/finance/payments'),
  getFinanceCustomers: () => request<any[]>('/finance/customers'),
  getFinanceReceivables: () => request<any[]>('/finance/receivables'),
  getFinanceBudgets: () => request<any[]>('/finance/budgets'),
  getFinanceBudgetLines: (budgetId: string) => request<any[]>(`/finance/budgets/${budgetId}/lines`),
  getFinanceForecasts: () => request<any[]>('/finance/forecasts'),
  getFinanceExpenseReports: () => request<any[]>('/finance/expense-reports'),
  getFinanceExpenseItems: (reportId: string) => request<any[]>(`/finance/expense-reports/${reportId}/items`),
  getFinanceBankAccounts: () => request<any[]>('/finance/bank-accounts'),
  getFinanceCashFlow: () => request<any[]>('/finance/cash-flow'),
  getFinanceTaxFilings: () => request<any[]>('/finance/tax/filings'),
  getFinanceTaxRules: () => request<any[]>('/finance/tax/rules'),
  getFinanceReports: () => request<any[]>('/finance/reports'),
  getFinanceAuditFindings: () => request<any[]>('/finance/audit/findings'),
  getFinanceSOXControls: () => request<any[]>('/finance/sox-controls'),
  getFinanceComplianceRules: () => request<any[]>('/finance/compliance-rules'),
  runFinanceAPAgent: (invoiceId: string) => request<any>(`/finance/invoices/${invoiceId}/match`, { method: 'POST' }),
  runFinanceARAgent: (invoiceId: string) => request<any>(`/finance/receivables/${invoiceId}/dunning`, { method: 'POST' }),

  // ─── Executive Command Center APIs ───
  getExecutiveOverview: () => request<any>('/executive/overview'),
  getExecutiveHealth: () => request<any>('/executive/health'),
  getExecutiveRisks: () => request<any>('/executive/risks'),
  getExecutivePredictions: () => request<any[]>('/executive/predictions'),
  getExecutiveTrust: () => request<any>('/executive/trust'),
  getExecutiveStory: () => request<any>('/executive/story'),

  // ─── Legal Department APIs ───
  getLegalDashboard: () => request<any>('/legal/dashboard'),
  getLegalMatters: () => request<any[]>('/legal/matters'),
  getLegalContracts: () => request<any[]>('/legal/contracts'),
  getLegalClauses: (contractId: string) => request<any[]>(`/legal/contracts/${contractId}/clauses`),
  runContractReviewAgent: (contractId: string) => request<any>(`/legal/contracts/${contractId}/review`, { method: 'POST' }),
  getLegalObligations: () => request<any[]>('/legal/compliance/obligations'),
  runComplianceAuditAgent: (obligationId: string) => request<any>(`/legal/compliance/obligations/${obligationId}/audit`, { method: 'POST' }),
  getLegalCases: () => request<any[]>('/legal/cases'),
  runLitigationAgent: (caseId: string) => request<any>(`/legal/cases/${caseId}/evaluate`, { method: 'POST' }),
  getLegalDsars: () => request<any[]>('/legal/privacy/dsars'),
  runPrivacyDsarAgent: (dsarId: string) => request<any>(`/legal/privacy/dsars/${dsarId}/validate`, { method: 'POST' }),
  getLegalPatents: () => request<any[]>('/legal/ip/patents'),
  runPatentEvalAgent: (patentId: string) => request<any>(`/legal/ip/patents/${patentId}/evaluate`, { method: 'POST' }),

  // ─── Support Department APIs ───
  getSupportDashboard: () => request<any>('/support/dashboard'),
  getSupportTickets: () => request<any[]>('/support/tickets'),
  runSupportTriageAgent: (ticketId: string) => request<any>(`/support/tickets/${ticketId}/triage`, { method: 'POST' }),
  runSupportResolutionAgent: (ticketId: string) => request<any>(`/support/tickets/${ticketId}/solve`, { method: 'POST' }),
  runSupportEscalationAgent: (ticketId: string) => request<any>(`/support/tickets/${ticketId}/escalate`, { method: 'POST' }),
  getSupportKBArticles: () => request<any[]>('/support/kb/articles'),
  getSupportCSATSurveys: () => request<any[]>('/support/csat/surveys'),
  runSupportFeedbackAgent: (surveyId: string) => request<any>(`/support/csat/${surveyId}/analyze`, { method: 'POST' }),
  getSupportSLAMetrics: () => request<any[]>('/support/sla/metrics'),
  runSupportSLACheck: () => request<any>('/support/sla/check', { method: 'POST' }),

  // ─── Sales Department APIs ───
  getSalesDashboard: () => request<any>('/sales/dashboard'),
  getSalesLeads: () => request<any[]>('/sales/leads'),
  runSalesLeadScoringAgent: (leadId: string) => request<any>(`/sales/leads/${leadId}/score`, { method: 'POST' }),
  getSalesAccounts: () => request<any[]>('/sales/accounts'),
  runSalesAccountAgent: (accountId: string) => request<any>(`/sales/accounts/${accountId}/health`, { method: 'POST' }),
  getSalesOpportunities: () => request<any[]>('/sales/opportunities'),
  runSalesPipelineAgent: (opportunityId: string) => request<any>(`/sales/opportunities/${opportunityId}/coach`, { method: 'POST' }),
  getSalesForecasts: () => request<any[]>('/sales/forecasts'),
  runSalesForecastAgent: (forecastId: string) => request<any>(`/sales/forecasts/${forecastId}/predict`, { method: 'POST' }),

  // ─── Operations Department APIs ───
  getOperationsDashboard: () => request<any>('/operations/dashboard'),
  // Engineering & IT Ops
  getEngineeringDashboard: () => request<any>('/engineering/dashboard'),
  getEngineeringServices: (health?: string) =>
    request<any[]>(`/engineering/services${health ? `?health=${health}` : ''}`),
  getEngineeringService: (id: string) => request<any>(`/engineering/services/${id}`),
  getEngineers: () => request<any[]>('/engineering/engineers'),
  getPullRequests: (status?: string) =>
    request<any[]>(`/engineering/pull-requests${status ? `?status=${status}` : ''}`),
  runCodeReviewAgent: (prId: string) =>
    request<any>(`/engineering/pull-requests/${prId}/review`, { method: 'POST' }),
  getDeployments: (environment?: string) =>
    request<any[]>(`/engineering/deployments${environment ? `?environment=${environment}` : ''}`),
  runDeployRiskAgent: (deploymentId: string) =>
    request<any>(`/engineering/deployments/${deploymentId}/assess`, { method: 'POST' }),
  getIncidents: (params?: { status?: string; severity?: string }) => {
    const q = new URLSearchParams(
      Object.entries(params || {}).filter(([, v]) => !!v) as [string, string][]
    ).toString();
    return request<any[]>(`/engineering/incidents${q ? `?${q}` : ''}`);
  },
  getIncident: (id: string) => request<any>(`/engineering/incidents/${id}`),
  runIncidentTriageAgent: (incidentId: string) =>
    request<any>(`/engineering/incidents/${incidentId}/triage`, { method: 'POST' }),
  getPostmortems: () => request<any[]>('/engineering/postmortems'),

  getOperationsProjects: () => request<any[]>('/operations/projects'),
  runOperationsProjectAgent: (taskId: string) => request<any>(`/operations/projects/tasks/${taskId}/evaluate`, { method: 'POST' }),
  getOperationsResources: () => request<any[]>('/operations/resources'),
  runOperationsResourceAgent: (allocationId: string) => request<any>(`/operations/resources/allocations/${allocationId}/check`, { method: 'POST' }),
  getOperationsVendors: () => request<any[]>('/operations/vendors'),
  runOperationsVendorAgent: (contractId: string) => request<any>(`/operations/vendors/${contractId}/evaluate`, { method: 'POST' }),
  getOperationsProcurements: () => request<any[]>('/operations/procurements'),
  runOperationsProcurementAgent: (requestId: string) => request<any>(`/operations/procurements/${requestId}/audit`, { method: 'POST' }),
  getOperationsInspections: () => request<any[]>('/operations/inspections'),
  runOperationsQualityAgent: (inspectionId: string) => request<any>(`/operations/inspections/${inspectionId}/audit`, { method: 'POST' }),

  // Connector Health & Feed (replaces mock data)
  getConnectorHealth: (id: string) => request<any>(`/connectors/${id}/health`),
  getConnectorFeed: (id: string, limit?: number) => request<any>(`/connectors/${id}/feed${limit ? `?limit=${limit}` : ''}`),

  // ─── AI Foundry (v2, Phase 2: Learning Intelligence) ───
  // Curates the platform's governed execution history into an exportable
  // training dataset, and captures the human corrections that make the
  // strongest training signal. Tenant-scoped + RLS.
  getFoundryStats: () => request<FoundryStats>('/foundry/datasets'),
  buildFoundryDataset: (opts?: { include_negative?: boolean; limit?: number }) =>
    request<FoundryBuildResult>('/foundry/datasets/build', {
      method: 'POST', body: JSON.stringify(opts || {}),
    }),
  recordFoundryFeedback: (body: FoundryFeedbackInput) =>
    request<{ id: string; evaluation_label: string; quality_score: number; source: string }>(
      '/foundry/feedback', { method: 'POST', body: JSON.stringify(body) }),
  exportFoundryDataset: (params?: { domain?: string; min_quality?: number; positive_only?: boolean; limit?: number }) => {
    const q = new URLSearchParams(
      Object.entries(params || {}).filter(([, v]) => v !== undefined && v !== '').map(([k, v]) => [k, String(v)])
    ).toString();
    return request<{ tenant_id: string; count: number; examples: FoundryExample[] }>(
      `/foundry/datasets/export${q ? `?${q}` : ''}`);
  },

  // ─── Domain Analytics & Workflow Layer (shared across the 7 domains) ───
  // Every domain exposes the same computed-analytics shape and a declared
  // state machine; the DomainAnalytics / WorkflowActions components render
  // all seven domains from these four calls.
  getDomainAnalytics: (domain: string) => request<DomainAnalytics>(`/${domain}/analytics`),
  getDomainWorkflows: (domain: string) => request<Record<string, WorkflowSpec>>(`/${domain}/workflows`),
  getWorkflowEvents: (domain: string, params?: { entity_type?: string; entity_id?: string }) => {
    const q = new URLSearchParams(
      Object.entries(params || {}).filter(([, v]) => !!v) as [string, string][]
    ).toString();
    return request<WorkflowEvent[]>(`/${domain}/workflow-events${q ? `?${q}` : ''}`);
  },
  transitionEntity: (domain: string, entityPath: string, id: string, to_state: string, note?: string) =>
    request<TransitionResult>(`/${domain}/${entityPath}/${id}/transition`, {
      method: 'POST', body: JSON.stringify({ to_state, note: note || null }),
    }),
  createDomainEntity: (domain: string, entityPath: string, body: Record<string, any>) =>
    request<any>(`/${domain}/${entityPath}`, { method: 'POST', body: JSON.stringify(body) }),
  getOrgPulse: () => request<OrgPulse>('/org/pulse'),
  getOrgActivity: (limit = 50) => request<WorkflowEvent[]>(`/org/activity?limit=${limit}`),
  getOrgStale: (domain?: string) =>
    request<{ count: number; breaches: SLABreach[] }>(`/org/stale${domain ? `?domain=${domain}` : ''}`),
  escalateStale: (domain?: string) =>
    request<{ escalated: number; skipped_open: number; breaches: number }>(
      `/org/stale/escalate${domain ? `?domain=${domain}` : ''}`, { method: 'POST' }),

  // ─── Workspace: assignment, comments, my-work, workload (Sprints 6-7) ───
  assignEntity: (entityType: string, id: string, assignee: string, note?: string) =>
    request<any>(`/org/entities/${entityType}/${id}/assign`, {
      method: 'POST', body: JSON.stringify({ assignee, note: note || null }) }),
  unassignEntity: (entityType: string, id: string) =>
    request<any>(`/org/entities/${entityType}/${id}/assign`, { method: 'DELETE' }),
  getAssignment: (entityType: string, id: string) =>
    request<{ assignee: string | null }>(`/org/entities/${entityType}/${id}/assignment`),
  getMyWork: () => request<{ assignee: string; items: MyWorkItem[] }>('/org/my-work'),
  getWorkload: () => request<{ workload: { assignee: string; count: number }[] }>('/org/workload'),
  getComments: (entityType: string, id: string) =>
    request<EntityComment[]>(`/org/entities/${entityType}/${id}/comments`),
  addComment: (entityType: string, id: string, body: string) =>
    request<EntityComment>(`/org/entities/${entityType}/${id}/comments`, {
      method: 'POST', body: JSON.stringify({ body }) }),
  deleteComment: (commentId: string) =>
    request<any>(`/org/comments/${commentId}`, { method: 'DELETE' }),

  // ─── Notifications (Sprint 9) ───
  getNotifications: (unreadOnly = false, limit = 50) =>
    request<{ counts: { unread: number; action_required: number }; items: AppNotification[] }>(
      `/org/notifications?unread_only=${unreadOnly}&limit=${limit}`),
  markNotificationsRead: (ids: string[]) =>
    request<{ marked: number }>('/org/notifications/read', {
      method: 'POST', body: JSON.stringify({ ids }) }),
  resolveNotification: (id: string) =>
    request<any>(`/org/notifications/${id}/resolve`, { method: 'POST' }),
  getDigest: () => request<any>('/org/digest'),

  // ─── Automation rules (Sprint 8) ───
  getAutomationRules: () => request<AutomationRule[]>('/org/rules'),
  createAutomationRule: (body: Partial<AutomationRule>) =>
    request<AutomationRule>('/org/rules', { method: 'POST', body: JSON.stringify(body) }),
  toggleAutomationRule: (id: string, active: boolean) =>
    request<AutomationRule>(`/org/rules/${id}?is_active=${active}`, { method: 'PATCH' }),
  deleteAutomationRule: (id: string) => request<any>(`/org/rules/${id}`, { method: 'DELETE' }),
  runAutomationRules: (ruleId?: string) =>
    request<{ rules_evaluated: number; actions_fired: number; results: any[] }>(
      `/org/rules/run${ruleId ? `?rule_id=${ruleId}` : ''}`, { method: 'POST' }),

  // ─── Saved segments + CSV export (Sprint 10) ───
  getSegments: (domain?: string) =>
    request<SavedSegment[]>(`/org/segments${domain ? `?domain=${domain}` : ''}`),
  createSegment: (body: Partial<SavedSegment>) =>
    request<SavedSegment>('/org/segments', { method: 'POST', body: JSON.stringify(body) }),
  deleteSegment: (id: string) => request<any>(`/org/segments/${id}`, { method: 'DELETE' }),
  exportCsvUrl: (entityType: string) => `${API_BASE}/org/export/${entityType}.csv`,
  bulkTransition: (domain: string, entityType: string, ids: string[], to_state: string, note?: string) =>
    request<BulkTransitionResult>(`/${domain}/workflows/${entityType}/bulk-transition`, {
      method: 'POST', body: JSON.stringify({ ids, to_state, note: note || null }),
    }),

  // ─── WebSocket helper (returns URL, not a fetch) ───
  // The ws router is mounted at the server root (/ws/...), NOT under /api/v1.
  getWebSocketUrl: (path: string) => {
    const wsBase = (import.meta.env.VITE_API_BASE || `http://${window.location.hostname}:8001/api/v1`)
      .replace(/^http/, 'ws')
      .replace(/\/api\/v1\/?$/, '');
    const token = localStorage.getItem('kaeos-token');
    // SECURITY (log-leak surface): the JWT rides in the query string because the
    // browser WebSocket API cannot set an Authorization header on the handshake.
    // Query strings are prone to landing in proxy/server access logs and browser
    // history, so this token is more exposed than the Bearer header used for REST.
    // Prefer a header/subprotocol path (e.g. Sec-WebSocket-Protocol carrying the
    // token, or a short-lived single-use ticket minted via REST then redeemed on
    // connect) IF the backend adds support - do not change this without a matching
    // server-side handler, or live connections will break.
    return `${wsBase}${path}${token ? `?token=${encodeURIComponent(token)}` : ''}`;
  },
};


