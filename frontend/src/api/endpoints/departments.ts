import { request } from '../http';
import type { HRCandidate, HREmployee, HRPerformanceReview, HRRequisition, HRTimeOffRequest } from '../types';

export const departmentsApi = {
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

  // Precog — forecast the north-star (safe-autonomy) + volume with confidence bands
  getForecast: (days = 45, horizon = 14) => request<any>(`/metrics/forecast?days=${days}&horizon=${horizon}`),

  // Foresight — the autonomous, prescriptive reality lane (Shock/What-if/Wargame/
  // Replay are reactive; these run with no prompt and rank what to worry about).
  getPremortemRadar: (signalDays = 90, limit = 8) =>
    request<any>(`/foresight/premortem?signal_days=${signalDays}&limit=${limit}`),
  getForesightTrajectory: (days = 45) => request<any>(`/foresight/trajectory?days=${days}`),
  commissionGapCloser: (scenario: string) =>
    request<any>('/foresight/commission', { method: 'POST', body: JSON.stringify({ scenario }) }),

  // Predictive Ops — zero-prompt "ghost" executions: what the org is about to do
  getGhostExecutions: () => request<any>('/predictive/ghost-executions'),

  // Autonomy Wargaming — adversarial cascade resilience scoring
  getWargamePlaybooks: () => request<any>('/wargame/playbooks'),
  runWargame: (playbook: string) => request<any>('/wargame/run', { method: 'POST', body: JSON.stringify({ playbook }) }),

  // Time Machine — decision replay + counterfactual recompute of the north-star
  getDecisionTimeline: (days = 45, limit = 200) => request<any>(`/time-machine/timeline?days=${days}&limit=${limit}`),
  getStateAsOf: (at: string, days = 45) => request<any>(`/time-machine/state?at=${encodeURIComponent(at)}&days=${days}`),
  runCounterfactual: (executionId: string, flip: 'approve' | 'fail' | 'escalate', days = 45) =>
    request<any>('/time-machine/counterfactual', { method: 'POST', body: JSON.stringify({ execution_id: executionId, flip, days }) }),

  // Causal Discovery — likely causal links between departments from real data
  getCausalLinks: (days = 45, minStrength = 0.4) => request<any>(`/causal/discover?days=${days}&min_strength=${minStrength}`),

  // Regulatory & Risk Autopilot — risk register, control map, evidence packs
  getRegulatoryOverview: (days = 30) => request<any>(`/regulatory/overview?days=${days}`),
  getRegulatoryEvidence: (framework: string, days = 90) =>
    request<any>(`/regulatory/evidence/${framework}?days=${days}`),

  // Audit-readiness controls evidence + DSAR erasure (admin)
  getControlsReport: () => request<any>('/compliance/controls'),
  eraseSubject: (body: { employee_id?: string; email?: string }) =>
    request<any>('/privacy/erasure', { method: 'POST', body: JSON.stringify(body) }),
  replayErasures: () => request<any>('/privacy/erasure/replay', { method: 'POST' }),

  // Event Mesh — external signals correlated to the twin, with governed responses
  getMeshSignals: (limit = 50) => request<any>(`/signals?limit=${limit}`),
  ingestMeshSignal: (payload: { kind: string; title: string; severity?: string; source?: string; body?: string }) =>
    request<any>('/signals/ingest', { method: 'POST', body: JSON.stringify(payload) }),
  // Enact the governed response for a correlated signal. The backend could
  // always do this; until now nothing in the UI could trigger it, so a signal
  // that correlated to the twin had no way to be acted on.
  respondToMeshSignal: (signalId: string) =>
    request<any>(`/signals/${signalId}/respond`, { method: 'POST' }),

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
  getConnectorFeed: (id: string, limit?: number) => request<any>(`/connectors/${id}/feed${limit ? `?limit=${limit}` : ''}`)
};
