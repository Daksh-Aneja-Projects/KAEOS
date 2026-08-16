import { request } from '../http';
import type { BenchmarkData, BillingEntitlements, CandidateRule, ComplianceDashboard, ConflictItem, ConnectorCredentialStatus, ConnectorCredentialsBody, ConnectorsResponse, ElicitationDashboard, ExecutionItem, FederatedConfigItem, GraphData, KBHealth, LLMConfigInput, LLMConfigItem, MCPToolInput, MCPToolItem, MarketplaceItem, ModelCapabilityProfile, NotificationChannel, NotificationDelivery, NotificationKind, OntologyConfigItem, PendingHITLItem, ProvenanceEntry, RedTeamScan, RuleItem, RuleListResponse, SecurityLog, Signal, SkillItem, SkillRegistryResponse, SkillValueBaseline } from '../types';

export const governanceApi = {
  // Auth
  authMe: () => request<any>('/auth/me'),
  authLogin: (credentials: any) => request<any>('/auth/login', { method: 'POST', body: JSON.stringify(credentials) }),
  authUsers: () => request<any>('/auth/users'),
  authCreateUser: (data: any) => request<any>('/auth/users', { method: 'POST', body: JSON.stringify(data) }),
  authUpdateRole: (id: string, role: string) => request<any>(`/auth/users/${id}/role`, { method: 'PUT', body: JSON.stringify({ role }) }),
  /** Set (or clear with null) a user's department scope - ADMIN only.
   *  The scope rides in the JWT, so it applies from the user's next login. */
  updateUserDepartment: (id: string, department: string | null) =>
    request<{ id: string; email: string; department: string | null; note: string }>(
      `/auth/users/${id}/department`, { method: 'PUT', body: JSON.stringify({ department }) }),
  authDeleteUser: (id: string) => request<any>(`/auth/users/${id}`, { method: 'DELETE' }),
  authReactivateUser: (id: string) => request<any>(`/auth/users/${id}/reactivate`, { method: 'POST' }),
  authInviteUser: (data: { email: string; display_name?: string; role?: string; department?: string | null }) =>
    request<any>('/auth/users/invite', { method: 'POST', body: JSON.stringify(data) }),
  /** Public: redeem an invite token and set the first password. */
  acceptInvite: (body: { token: string; password: string }) =>
    request<{ id: string; email: string; is_active: boolean }>('/auth/accept-invite', {
      method: 'POST', body: JSON.stringify(body) }),
  /** Server-side token revocation. Best-effort - the client drops its token regardless. */
  authLogout: () => request<{ revoked: boolean }>('/auth/logout', { method: 'POST' }),

  // MFA (self-service)
  mfaStatus: () => request<{ enrolled: boolean; enabled: boolean }>('/auth/mfa/status'),
  mfaEnroll: () => request<{ secret: string; otpauth_uri: string }>('/auth/mfa/enroll', { method: 'POST' }),
  mfaConfirm: (code: string) => request<any>('/auth/mfa/confirm', { method: 'POST', body: JSON.stringify({ code }) }),
  mfaDisable: () => request<any>('/auth/mfa/disable', { method: 'POST' }),

  // Data governance — DSAR erasure, retention (privacy.py)
  privacyErasure: (body: { employee_id?: string; email?: string }) => request<any>('/privacy/erasure', { method: 'POST', body: JSON.stringify(body) }),
  getRetention: () => request<{ policies: any[] }>('/privacy/retention'),
  setRetention: (body: { data_class: string; retain_days: number; enabled: boolean }) => request<any>('/privacy/retention', { method: 'PUT', body: JSON.stringify(body) }),
  applyRetention: () => request<any>('/privacy/retention/apply', { method: 'POST' }),

  // Billing / usage (billing.py)
  getBillingUsage: () => request<any>('/billing/usage'),
  getBillingRoi: () => request<any>('/billing/roi'),
  /** Plan, feature grants, current-period usage vs allowance, plan catalog, purchased seats. */
  getBillingEntitlements: () => request<BillingEntitlements>('/billing/entitlements'),
  /** Hosted checkout URL for a paid plan. Admin-only; 404 when no billing provider (self-host). */
  createCheckoutSession: (plan: string) =>
    request<{ url: string }>('/billing/checkout-session', { method: 'POST', body: JSON.stringify({ plan }) }),
  /** Hosted billing-portal URL (payment method, invoices, cancellation). Admin-only; 404 on self-host. */
  createPortalSession: () => request<{ url: string }>('/billing/portal-session', { method: 'POST' }),
  /** Per-skill human baselines that power the honest "Value delivered" ROI figure. */
  getBaselines: () => request<{ baselines: SkillValueBaseline[] }>('/billing/baselines'),
  putBaseline: (body: { skill_name: string; baseline_minutes: number; hourly_rate?: number }) =>
    request<SkillValueBaseline>('/billing/baselines', { method: 'PUT', body: JSON.stringify(body) }),

  // Webhooks (enterprise.py — router mounts at /api/v1, so no /enterprise segment)
  getWebhooks: () => request<{ subscriptions: any[] }>('/webhooks'),
  createWebhook: (body: { name: string; endpoint: string; events: string[] }) => request<any>('/webhooks', { method: 'POST', body: JSON.stringify(body) }),
  deleteWebhook: (id: string) => request<any>(`/webhooks/${id}`, { method: 'DELETE' }),

  // Platform API keys (enterprise.py) — self-service, tenant-scoped, admin-only
  getApiKeys: () => request<{ keys: any[] }>('/api-keys'),
  createApiKey: (body: { name: string; role: string }) => request<{ api_key: string; key_id: string; role: string }>('/api-keys', { method: 'POST', body: JSON.stringify(body) }),
  revokeApiKey: (keyId: string) => request<any>(`/api-keys/${keyId}`, { method: 'DELETE' }),

  // Notification channels (notifications.py) — SMTP / Slack / webhook fan-out
  getNotificationEvents: () => request<{ events: string[]; kinds: NotificationKind[] }>('/notifications/events'),
  getNotificationChannels: () => request<{ channels: NotificationChannel[] }>('/notifications/channels'),
  createNotificationChannel: (body: { name: string; kind: NotificationKind; config: Record<string, any>; events: string[]; enabled: boolean }) =>
    request<NotificationChannel>('/notifications/channels', { method: 'POST', body: JSON.stringify(body) }),
  updateNotificationChannel: (id: string, body: { name?: string; config?: Record<string, any>; events?: string[]; enabled?: boolean }) =>
    request<NotificationChannel>(`/notifications/channels/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteNotificationChannel: (id: string) => request<void>(`/notifications/channels/${id}`, { method: 'DELETE' }),
  testNotificationChannel: (id: string) => request<{ ok: boolean; error: string | null }>(`/notifications/channels/${id}/test`, { method: 'POST' }),
  getNotificationDeliveries: (limit: number = 50) => request<{ deliveries: NotificationDelivery[] }>(`/notifications/deliveries?limit=${limit}`),

  // SSO (OIDC) — discovery is unauthenticated (used by the login page)
  discoverSSO: (email: string) => request<{ sso: boolean; provider_label?: string; tenant_id?: string; authorize_url?: string }>(`/auth/sso/discover?email=${encodeURIComponent(email)}`),
  getSSOConnections: () => request<{ connections: any[] }>('/auth/sso/connections'),
  upsertSSOConnection: (data: any) => request<any>('/auth/sso/connections', { method: 'POST', body: JSON.stringify(data) }),
  deleteSSOConnection: (id: string) => request<any>(`/auth/sso/connections/${id}`, { method: 'DELETE' }),

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
  getAutonomy: () => request<{ domain: string; min_confidence: number; is_default: boolean; auto_managed?: boolean }[]>('/config/autonomy'),
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
  })
};
