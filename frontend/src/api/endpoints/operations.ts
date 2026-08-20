import { request, uploadForm, API_BASE } from '../http';
import type { AppNotification, AutomationRule, BulkTransitionResult, DomainAnalytics, EntityComment, FoundryBuildResult, FoundryExample, FoundryFeedbackInput, FoundryStats, MyWorkItem, OrgPulse, RuleItem, SLABreach, SavedSegment, TransitionResult, WorkflowEvent, WorkflowSpec } from '../types';

/** The full outbound write-back status set (models/sync.py OutboundWrite.status). */
export type OutboundStatus =
  | 'PENDING' | 'SENT' | 'FAILED' | 'DEAD'
  | 'SKIPPED_NO_CONNECTOR' | 'SKIPPED_NO_CREDENTIALS';

/** A facility work order — bound to app/operations/api/v1/router.py's
 * /operations/work-orders shape (WorkOrder model). */
export interface WorkOrderRow {
  id: string;
  facility_name: string;
  issue_title: string;
  description: string | null;
  category: string;             // MAINTENANCE | SAFETY | DECOMMISSION
  severity: string | null;
  status: string;                // OPEN | IN_PROGRESS | RESOLVED | CLOSED
  priority: string | null;       // URGENT | MEDIUM | LOW | NEEDS_TRIAGE (set by FacilityAgent)
  assigned_team: string | null;
  scheduled_hours: number | null;
  safety_flagged: boolean;
  reported_by: string | null;
  ai_notes: string | null;
  created_at: string | null;
  resolved_at: string | null;
}

export const operationsApi = {
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

  // Foundry Phase 3 — model evolution + the external fine-tune bridge. The whole
  // gated-promotion loop existed and was tested server-side but had no UI, so a
  // candidate model could never actually be evaluated or promoted from the app.
  // Promotion stays human-gated: a run must win a NON-simulated evaluation.
  listEvolutionRuns: (limit = 20) => request<any>(`/foundry/evolution/runs?limit=${limit}`),
  getEvolutionRun: (runId: string) => request<any>(`/foundry/evolution/runs/${runId}`),
  evaluateCandidateModel: (payload: { tier: string; candidate_model: string; baseline_model?: string; eval_limit?: number }) =>
    request<any>('/foundry/evolution/evaluate', { method: 'POST', body: JSON.stringify(payload) }),
  promoteEvolutionRun: (runId: string) =>
    request<any>(`/foundry/evolution/runs/${runId}/promote`, { method: 'POST' }),
  rejectEvolutionRun: (runId: string) =>
    request<any>(`/foundry/evolution/runs/${runId}/reject`, { method: 'POST' }),
  listFinetuneJobs: (limit = 20) => request<any>(`/foundry/finetune/jobs?limit=${limit}`),
  submitFinetune: (payload: { tier: string }) =>
    request<any>('/foundry/finetune/submit', { method: 'POST', body: JSON.stringify(payload) }),
  pollFinetuneJobs: () => request<any>('/foundry/finetune/poll', { method: 'POST' }),

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
  // ─── Operations: facility work orders (FacilityAgent) ───
  // Create uses the generic createDomainEntity('operations', 'work-orders', body).
  getOperationsWorkOrders: () => request<WorkOrderRow[]>('/operations/work-orders'),
  triageOperationsWorkOrder: (workOrderId: string) =>
    request<any>(`/operations/work-orders/${workOrderId}/triage`, { method: 'POST' }),

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

  // ─── Domain pack install / uninstall (workforce/api/domain_packs.py) ───
  // Both take no body; install is idempotent (re-install refreshes the version).
  installDomainPack: (packId: string) =>
    request<{ status: string; installation_id: string; message: string }>(
      `/workforce/packs/${packId}/install`, { method: 'POST' }),
  uninstallDomainPack: (packId: string) =>
    request<{ status: string; message: string }>(
      `/workforce/packs/${packId}/uninstall`, { method: 'POST' }),

  // ─── Rules authoring (rules.py) ───
  createRule: (body: {
    statement: string; trigger_json: Record<string, any>; action_json: Record<string, any>;
    domain?: string | null; workflow_id?: string | null; exceptions_json?: any[];
    compliance_tags?: string[]; half_life_days?: number; access_level?: string;
  }) => request<RuleItem>('/rules', { method: 'POST', body: JSON.stringify(body) }),
  /** Human validation event. Every field has a server default, so `{}` is valid. */
  validateRule: (ruleId: string, body?: { validator_role?: string; validator_hash?: string; new_tier?: string }) =>
    request<RuleItem>(`/rules/${ruleId}/validate`, { method: 'PUT', body: JSON.stringify(body || {}) }),

  // ─── Skills authoring (skills.py + federated.py) ───
  compileSkill: (body: { workflow_id: string; domain: string; workflow_name: string; required_tools?: string[] }) =>
    request<{ status: string; skill_id: string; yaml: string }>('/skills/compile', {
      method: 'POST', body: JSON.stringify(body) }),
  /** Plain-English account of what a skill actually did. No body; {skill_id} is the NAME. */
  explainSkill: (skillId: string) =>
    request<{ summary: string; steps_taken: any[]; confidence_narrative: string; human_validators: any[]; degraded?: boolean }>(
      `/skills/${skillId}/explain`, { method: 'POST' }),
  /** Share a proven skill (>=90% success) to the federation. {skill_id} is the NAME. */
  federatedExportSkill: (skillId: string) =>
    request<{ status: string; skill_id: string; ledger_receipt: string }>(
      `/federated/export-skill/${skillId}`, { method: 'POST' }),

  // ─── Provenance integrity ───
  // chain_valid is null when nothing can be cryptographically judged
  // (pre-unification legacy rows, or an empty chain) - honest three-state.
  verifyProvenance: (ruleId: string) =>
    request<{
      rule_id: string; chain_valid: boolean | null;
      status: 'VERIFIED' | 'TAMPERED' | 'LEGACY_UNVERIFIABLE' | 'EMPTY';
      total: number; verified: number; legacy: number;
    }>(`/provenance/${ruleId}/verify`),

  // ─── Actuation reconciliation (operator) ───
  reconcileActuation: () =>
    request<{ drift_count: number; reconciled: number; skipped: number; details: any[] }>(
      '/actuation/reconcile', { method: 'POST' }),

  // ─── Circuit breaker reset (operator) ───
  resetAgentCircuit: (agentName: string) =>
    request<{ status: string; agent_name: string }>(
      `/infrastructure/agents/${encodeURIComponent(agentName)}/circuit/reset`, { method: 'POST' }),

  // ─── Integration sync plane (sync.py) ───
  /** Rotates and returns the HMAC signing secret. Shown once, never readable again. */
  rotateWebhookSecret: (connectorId: string) =>
    request<{ connector_id: string; webhook_secret: string; ingest_url: string; note: string }>(
      `/integrations/${connectorId}/webhook-secret`, { method: 'POST' }),
  getSyncLedger: (limit = 50) => request<{ ledger: any[] }>(`/integrations/sync/ledger?limit=${limit}`),
  /** counts is ALWAYS the full per-status tally for the tenant (statuses with
   *  zero rows are absent), even when the row list is filtered by ?status=. */
  getOutboundQueue: (limit = 50, status?: OutboundStatus) =>
    request<{ outbound: any[]; counts: Partial<Record<OutboundStatus, number>> }>(
      `/integrations/sync/outbound?limit=${limit}${status ? `&status=${status}` : ''}`),
  dispatchOutbound: () =>
    request<{ sent: number; failed: number; skipped: number }>(
      '/integrations/sync/outbound/dispatch', { method: 'POST' }),
  /** Operator replay of a DEAD/FAILED write: back to PENDING, fresh retry budget. */
  requeueOutbound: (id: string) =>
    request<{ id: string; status: string; attempts: number; idempotency_key: string | null }>(
      `/integrations/sync/outbound/${id}/requeue`, { method: 'POST' }),

  // ─── Elicitation question generation (operator) ───
  generateElicitationQuestion: (body: { employee_id: string; domain?: string | null }) =>
    request<{ status: string; question_id?: string; question?: string; message?: string }>(
      '/elicitation/generate', { method: 'POST', body: JSON.stringify(body) }),

  // ─── Operational digest (notifications.py) — days ride in the query string ───
  previewDigest: (days = 7) =>
    request<{ payload: Record<string, any>; text: string }>(`/notifications/digest/preview?days=${days}`),
  sendDigest: (days = 7) =>
    request<{ tenants: number; sent: number; failed: number }>(
      `/notifications/digest/send?days=${days}`, { method: 'POST' }),

  // ─── Sales: revenue-intelligence agents + commission ───
  runSalesChurnRiskAgent: (accountId: string) =>
    request<any>(`/sales/accounts/${accountId}/churn-risk`, { method: 'POST' }),
  runSalesProposalAgent: (opportunityId: string) =>
    request<any>(`/sales/opportunities/${opportunityId}/proposal`, { method: 'POST' }),
  /** CPQ takes its discount as a QUERY param (FastAPI Query(...)), not a body. */
  runSalesCpqAgent: (opportunityId: string, discountPct: number) =>
    request<any>(`/sales/opportunities/${opportunityId}/cpq?discount=${discountPct}`, { method: 'POST' }),
  getSalesCommissions: () => request<any[]>('/sales/commission'),
  paySalesCommission: (calculationId: string) =>
    request<{ calculation_id: string; deal_value: number; rate_applied: number; calculated_payout: number;
              is_approved: boolean; status: string; reason: string | null }>(
      `/sales/commission/${calculationId}/payout`, { method: 'POST' }),

  // ─── Support: autonomous resolution + KB authoring ───
  runSupportAutoResolveAgent: (ticketId: string) =>
    request<any>(`/support/tickets/${ticketId}/auto-resolve`, { method: 'POST' }),
  runSupportDocumentAgent: (ticketId: string) =>
    request<any>(`/support/tickets/${ticketId}/document`, { method: 'POST' }),

  // ─── Finance: chart of accounts ───
  getChartOfAccounts: (accountType?: string) =>
    request<any[]>(`/finance/chart-of-accounts${accountType ? `?account_type=${accountType}` : ''}`),

  // ─── Benchmark: LLM maturity report (pairs with getBenchmark) ───
  getIntelligenceReport: () =>
    request<{ report: Record<string, any>; org_snapshot: { total_rules: number; total_skills: number; avg_confidence: number } }>(
      '/benchmark/intelligence-report'),

  // ─── Advanced capabilities (advanced.py) ───
  ingestRegulation: (body: { framework_name: string; directive_text: string; urgency: string }) =>
    request<{ status: string; framework?: string; new_rules_synthesized?: number; rule_statements?: string[]; error?: string }>(
      '/advanced/ingest-regulation', { method: 'POST', body: JSON.stringify(body) }),
  getQuantumEvents: () => request<any[]>('/advanced/quantum-events'),
  getRegulatoryRules: () => request<any[]>('/advanced/regulatory-rules'),
  getFederatedExports: () => request<any[]>('/advanced/federated-exports'),
  getPolymorphicEvents: () => request<any[]>('/advanced/polymorphic-events'),
  forcePrecogCycle: () =>
    request<{ status: 'IDLE' | 'PROCESSED'; message?: string; signal?: string }>(
      '/advanced/precog/force-cycle', { method: 'POST' }),
  simulatePhysicsShock: (shockType: string) =>
    request<{ status: string; shock_type: string; nodes_affected: number; ripple_effect: any[] }>(
      '/advanced/physics/simulate', { method: 'POST', body: JSON.stringify({ shock_type: shockType }) }),

  // ─── Data pipeline (pipeline.py) ───
  getPipelineConnectors: () => request<{ connectors: { slug: string; name: string; category: string; auth_type: string; status: string }[] }>(
    '/pipeline/connectors/available'),
  getPipelineTransforms: () => request<{ nodes: { type: string; name: string; description: string }[] }>(
    '/pipeline/transforms/available'),
  runPipeline: (body: {
    connector_slug: string; connector_config: Record<string, any>;
    connector_credentials?: Record<string, any>; dag_config?: Record<string, any> | null;
    destination_type?: string; destination_config?: Record<string, any> | null;
  }) => request<{
    run_id: string; status: 'SUCCESS' | 'FAILED'; records_read?: number; records_written?: number;
    records_failed?: number; chunks_produced?: number; pii_detections?: number;
    error?: string; log: { timestamp: string; level: string; message: string }[];
  }>('/pipeline/run', { method: 'POST', body: JSON.stringify(body) }),

  // ─── Neural Map (departments around the company brain) ───
  getNeuralMap: () => request<any>('/neural/map'),
  getNeuralWorld: () => request<any>('/neural/world'),
  getNeuralBrainStats: () => request<any>('/neural/brain/stats'),
  getNeuralDeptGraph: (ref: string) => request<any>(`/neural/departments/${encodeURIComponent(ref)}/graph`),
  getAgentDossier: (id: string) => request<any>(`/neural/agents/${encodeURIComponent(id)}/dossier`),
  getSkillDossier: (skillId: string) => request<any>(`/neural/skills/${encodeURIComponent(skillId)}/dossier`),
  getNeuralHierarchy: () => request<any>('/neural/hierarchy'),
  neuralBrainSearch: (q: string) => request<any>(`/neural/brain/search?q=${encodeURIComponent(q)}`),
  neuralBrainIngest: (opts: { text?: string; domain?: string; file?: File }) => {
    const form = new FormData();
    if (opts.text) form.append('text', opts.text);
    if (opts.domain) form.append('domain', opts.domain);
    if (opts.file) form.append('file', opts.file);
    return uploadForm<{
      signal_id: string; stored_chars: number; source: string;
      embedded: boolean; grounding_ready: boolean; message: string;
    }>('/neural/brain/ingest', form);
  },

  // ─── Authenticated CSV export URLs (fetched via downloadFile, not <a href>) ───
  usersCsvPath: () => '/auth/users/export.csv',
  complianceCsvPath: () => '/dashboard/compliance/export',
  actionsLedgerCsvPath: (limit = 5000) => `/actuation/ledger/export?limit=${limit}`,
  provenanceLedgerCsvPath: () => '/provenance/global/ledger/export',
  orgEntityCsvPath: (entityType: string) => `/org/export/${entityType}.csv`,

  // ─── WebSocket helper (returns URL, not a fetch) ───
  // The ws router is mounted at the server root (/ws/...), NOT under /api/v1.
  getWebSocketUrl: (path: string) => {
    const wsBase = (import.meta.env.VITE_API_BASE || `http://${window.location.hostname}:8001/api/v1`)
      .replace(/^http/, 'ws')
      .replace(/\/api\/v1\/?$/, '');
    // The token is NOT put in the query string (it would leak into proxy/access
    // logs and browser history). It is carried in the Sec-WebSocket-Protocol
    // handshake header instead — see getWebSocketProtocols() + the server handler.
    return `${wsBase}${path}`;
  },
  /** WebSocket subprotocols carrying the bearer token: ['kaeos-bearer', <jwt>].
   *  The browser sends these as Sec-WebSocket-Protocol; the server reads the
   *  token from there and echoes 'kaeos-bearer' to complete the handshake. */
  getWebSocketProtocols: (): string[] | undefined => {
    const token = localStorage.getItem('kaeos-token');
    return token ? ['kaeos-bearer', token] : undefined;
  }
};
