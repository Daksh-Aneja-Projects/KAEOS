import { request } from '../http';

export const enterpriseApi = {
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
  // (webhooks + API keys live at bare /webhooks and /api-keys — the enterprise
  //  router mounts at /api/v1 with no /enterprise segment; see blocks above.)
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
  )
};
