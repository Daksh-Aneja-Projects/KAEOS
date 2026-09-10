import { request, requestPublic } from '../http';

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

// ─── KAEOS Enterprise: the Governed Execution & Proof Layer ───
// Every call below is an Enterprise capability. On open core the backend
// answers 402 with a plain sentence ("This is a KAEOS Enterprise capability
// ..."); the surface shows that sentence, never a blank that reads as data.
export const governedExecutionApi = {
  // Root-mounted public /status (no auth, no tenant data): the seam state lives there.
  getEnterpriseStatus: () => requestPublic<any>('/status'),
  // Proofs (F1)
  getProofLedgerSummary: () => request<any>('/proof/ledger/summary'),
  getProofRecords: (limit = 50) => request<any>(`/proof/records?limit=${limit}`),
  getProof: (subjectId: string) => request<any>(`/proof/${encodeURIComponent(subjectId)}`),
  verifyProofLedger: (limit = 500) => request<any>(`/proof/ledger/verify?limit=${limit}`),
  proofLedgerBundlePath: () => '/proof/ledger/bundle',
  proofBundlePath: (subjectId: string) => `/proof/${encodeURIComponent(subjectId)}/bundle`,
  // Trust ledger + ladder (F3)
  getTrustLedger: (limit = 50) => request<any>(`/trust/ledger?limit=${limit}`),
  getTrustEntry: (skillId: string) => request<any>(`/trust/ledger/${encodeURIComponent(skillId)}`),
  getLadder: () => request<any>('/trust/ladder'),
  getLadderEntry: (skillId: string) => request<any>(`/trust/ladder/${encodeURIComponent(skillId)}`),
  setLadderMode: (enforce: boolean) => request<any>('/trust/ladder/settings', {
    method: 'PUT', body: JSON.stringify({ enforce }),
  }),
  pinLadderTier: (skillId: string, tier: string, note = '') => request<any>(
    `/trust/ladder/${encodeURIComponent(skillId)}`, { method: 'PUT', body: JSON.stringify({ tier, note }) }),
  releaseLadderPin: (skillId: string) => request<any>(
    `/trust/ladder/${encodeURIComponent(skillId)}/pin`, { method: 'DELETE' }),
  getAssurance: () => request<any>('/trust/assurance'),
  // Rehearsals (F4)
  getRehearsals: (limit = 50) => request<any>(`/rehearsal?limit=${limit}`),
  getRehearsal: (executionId: string) => request<any>(`/rehearsal/${encodeURIComponent(executionId)}`),
  // Gateway (F5)
  getGatewayPrincipals: () => request<any>('/gateway/principals'),
  getGatewayContracts: (department?: string) => request<any>(
    `/gateway/contracts${department ? `?department=${encodeURIComponent(department)}` : ''}`),
  setPrincipalPolicy: (principal: string, body: { hourly_call_cap?: number | null; daily_spend_cap_usd?: number | null; disabled?: boolean; note?: string }) =>
    request<any>(`/gateway/principals/${encodeURIComponent(principal)}/policy`, { method: 'PUT', body: JSON.stringify(body) }),
  // Outcomes (F6)
  getOutcomes: (period?: string) => request<any>(`/billing/outcomes${period ? `?period=${period}` : ''}`),
  getOutcomeLines: (period?: string, outcomeClass?: string, limit = 100) => request<any>(
    `/billing/outcomes/lines?limit=${limit}${period ? `&period=${period}` : ''}${outcomeClass ? `&outcome_class=${outcomeClass}` : ''}`),
  outcomesExportPath: (period?: string) => `/billing/outcomes/export${period ? `?period=${period}` : ''}`,

  // Enterprise Ontology (F8+F9): object/property/link/value types + object sets
  listObjectTypes: () => request<any>('/ontology/object-types'),
  getObjectType: (apiName: string) => request<any>(`/ontology/object-types/${encodeURIComponent(apiName)}`),
  listPropertyTypes: (apiName: string) => request<any>(`/ontology/object-types/${encodeURIComponent(apiName)}/properties`),
  searchObjects: (objectType: string, body: { filter?: any; limit?: number; branch?: string }) =>
    request<any>(`/ontology/objects/${encodeURIComponent(objectType)}/search`, {
      method: 'POST', body: JSON.stringify(body),
    }),
  getObject: (objectType: string, pk: string) =>
    request<any>(`/ontology/objects/${encodeURIComponent(objectType)}/${encodeURIComponent(pk)}`),
  createObject: (objectType: string, body: { properties: Record<string, any>; markings?: string[] }) =>
    request<any>(`/ontology/objects/${encodeURIComponent(objectType)}`, {
      method: 'POST', body: JSON.stringify(body),
    }),
  updateObject: (objectType: string, pk: string, body: { changes: Record<string, any>; expected_versions: Record<string, number> }) =>
    request<any>(`/ontology/objects/${encodeURIComponent(objectType)}/${encodeURIComponent(pk)}`, {
      method: 'PATCH', body: JSON.stringify(body),
    }),
  bootstrapOntologyType: (which: string) => request<any>('/ontology/bootstrap', {
    method: 'POST', body: JSON.stringify({ which }),
  }),

  // Action Type registry (F10) - a typed front-door onto governed Skills
  listActionTypes: () => request<any>('/ontology/action-types'),
  getActionTypeSchema: (apiName: string) => request<any>(`/ontology/action-types/${encodeURIComponent(apiName)}/schema`),
  applyActionType: (apiName: string, body: { parameters: Record<string, any>; target_pk?: string | null }) =>
    request<any>(`/ontology/action-types/${encodeURIComponent(apiName)}/apply`, {
      method: 'POST', body: JSON.stringify(body),
    }),

  // Value Types (F8) - reusable constraints (regex | enum | min/max) a PropertyType can point at
  listValueTypes: () => request<any>('/ontology/value-types'),
  createValueType: (body: { api_name: string; display_name: string; base_type?: string; constraint?: Record<string, any> }) =>
    request<any>('/ontology/value-types', { method: 'POST', body: JSON.stringify(body) }),

  // Interfaces (F8) - a named, required-property shape an ObjectType can claim to implement
  listInterfaces: () => request<any>('/ontology/interfaces'),
  createInterface: (body: { api_name: string; display_name: string; required_properties?: { api_name: string; base_type?: string }[] }) =>
    request<any>('/ontology/interfaces', { method: 'POST', body: JSON.stringify(body) }),
  verifyConformance: (apiName: string) =>
    request<any>(`/ontology/object-types/${encodeURIComponent(apiName)}/verify-conformance`, { method: 'POST' }),

  // Link Types (F8) - typed, cardinality-checked relationships, traversed through the real graph store
  listLinkTypes: () => request<any>('/ontology/link-types'),
  createLinkType: (body: {
    api_name: string; source_object_type: string; target_object_type: string; relation: string;
    cardinality?: string; forward_name: string; reverse_name: string;
  }) => request<any>('/ontology/link-types', { method: 'POST', body: JSON.stringify(body) }),
  createLinkInstance: (apiName: string, body: { source_id: string; target_id: string; properties?: Record<string, any> }) =>
    request<any>(`/ontology/link-types/${encodeURIComponent(apiName)}/instances`, {
      method: 'POST', body: JSON.stringify(body),
    }),
  getLinkInstances: (apiName: string, nodeId: string, direction: 'forward' | 'reverse' = 'forward') =>
    request<any>(`/ontology/link-types/${encodeURIComponent(apiName)}/instances/${encodeURIComponent(nodeId)}?direction=${direction}`),

  // Object Sets (F8) - a saved handle onto a group of objects (static | dynamic | temporary | permanent)
  createObjectSet: (body: { object_type: string; kind: string; definition?: Record<string, any>; name?: string | null }) =>
    request<any>('/ontology/object-sets', { method: 'POST', body: JSON.stringify(body) }),
  getObjectSetMembers: (objectSetId: string) => request<any>(`/ontology/object-sets/${encodeURIComponent(objectSetId)}/members`),

  // Dataset Transactions (F11) - git-for-data branch/commit history for a connector dataset
  createDatasetBranch: (datasetId: string, body: { name: string; from_branch?: string }) =>
    request<any>(`/ontology/datasets/${encodeURIComponent(datasetId)}/branches`, {
      method: 'POST', body: JSON.stringify(body),
    }),
  getDatasetBranchHistory: (datasetId: string, branch: string = 'main') =>
    request<any>(`/ontology/datasets/${encodeURIComponent(datasetId)}/branches/${encodeURIComponent(branch)}/history`),
  beginDatasetTransaction: (datasetId: string, body: { txn_type: string; branch?: string; cursor_used?: Record<string, any> | null }) =>
    request<any>(`/ontology/datasets/${encodeURIComponent(datasetId)}/transactions`, {
      method: 'POST', body: JSON.stringify(body),
    }),
  commitDatasetTransaction: (txnId: string, recordCount: number = 0) =>
    request<any>(`/ontology/datasets/transactions/${encodeURIComponent(txnId)}/commit`, {
      method: 'POST', body: JSON.stringify({ record_count: recordCount }),
    }),
  abortDatasetTransaction: (txnId: string, reason?: string) =>
    request<any>(`/ontology/datasets/transactions/${encodeURIComponent(txnId)}/abort`, {
      method: 'POST', body: JSON.stringify({ reason }),
    }),

  // Committee Decisions (F2, the human half): named approvers, one ballot
  // each, pooled by the same arithmetic as the debate gate. A committee
  // convened with an execution_id decides that paused run.
  listCommittees: (executionId?: string) =>
    request<any>(`/decision/committees${executionId ? `?execution_id=${encodeURIComponent(executionId)}` : ''}`),
  // Every committee in the workspace: a governance-console read (operator+,
  // never an agent principal), so the backend answers 403 for a viewer.
  listAllCommittees: () => request<any>('/decision/committees/all'),
  getCommittee: (id: string) => request<any>(`/decision/committees/${encodeURIComponent(id)}`),
  createCommittee: (body: {
    subject: string; options: { key: string; label: string; summary?: string }[];
    criteria: { key: string; label: string; raw_weight: number; rationale?: string }[];
    performance: Record<string, Record<string, number>>; required_approvers: string[];
    execution_id?: string;
  }) => request<any>('/decision/committees', { method: 'POST', body: JSON.stringify(body) }),
  castCommitteeVote: (id: string, endorsements: Record<string, number>) =>
    request<any>(`/decision/committees/${encodeURIComponent(id)}/vote`, {
      method: 'POST', body: JSON.stringify({ endorsements }),
    }),

  // Agent Quality Evals (F12): a human's thumbs-up/down on a sealed run, the
  // triage queue, pinned regression cases and the deterministic suite.
  submitSkillFeedback: (body: { execution_id: string; skill_id_name: string; rating: 'up' | 'down'; note?: string }) =>
    request<any>('/evals/feedback', { method: 'POST', body: JSON.stringify(body) }),
  listSkillFeedback: (triageStatus?: string) =>
    request<any>(`/evals/feedback${triageStatus ? `?triage_status=${encodeURIComponent(triageStatus)}` : ''}`),
  promoteFeedback: (feedbackId: string, body: { expected_status: string; reference_text?: string; pass_threshold?: number }) =>
    request<any>(`/evals/feedback/${encodeURIComponent(feedbackId)}/promote`, {
      method: 'POST', body: JSON.stringify(body),
    }),
  listRegressionCases: () => request<any>('/evals/regression-cases'),
  runRegressionSuite: () => request<any>('/evals/regression-suite/run', { method: 'POST' }),

  // Evidence pack (F7): the RFP / AI-Act set read from the record, each
  // section labelled measured or self-assessed; the zip adds the proofs.
  getEvidenceSummary: (trailLimit = 25) => request<any>(`/evidence/pack/summary?trail_limit=${trailLimit}`),
  evidencePackPath: () => '/evidence/pack',
};

