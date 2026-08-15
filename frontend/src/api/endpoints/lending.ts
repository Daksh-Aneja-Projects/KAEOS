import { request } from '../http';

/* ─── Response shapes (bound to app/lending/api/v1/router.py) ─── */

/** Shared analytics shape (kpis / charts / insights). */
export interface DomainAnalyticsPayload {
  domain: string;
  kpis: { key: string; label: string; value: number | null; format: string; note?: string | null }[];
  charts: { key: string; title: string; type: string; items: { label: string; value: number }[] }[];
  insights: { severity: string; message: string }[];
}

export interface LoanApplicationRow {
  id: string;
  application_number: string;
  applicant_name: string;
  product: string;
  credit_purpose: string;
  amount: number;
  term_months: number | null;
  credit_score: number | null;
  annual_income: number | null;
  dti_ratio: number | null;
  status: string;                 // RECEIVED | IN_REVIEW | PENDING_HITL | APPROVED | DENIED | WITHDRAWN
  intake_score: number | null;
  protected_class?: Record<string, any>;
}

/** Result of POST /applications/{id}/underwrite (UnderwriterAgent). */
export interface UnderwriteResult {
  status: string;                 // "success" (clean pass) | PENDING_HITL | BLOCKED_* | ESCALATED_DEBATE
  application_id: string;
  decision?: string;              // APPROVE | DENY
  reasons?: string[];             // plain-English principal reasons (Reg B)
  rationale?: string | null;      // LLM plain-English explanation for the reviewer
  decision_id?: string;
  execution_id?: string;
  reason?: string;
  violations?: { framework: string; reason: string }[];
}

export interface AdverseActionRow {
  id: string;
  application_id: string;
  specific_reasons: string[];
  decision_date: string | null;
  sent_at: string | null;
  within_30_days: boolean | null;
}

export interface AdverseActionResult {
  status: string;                 // "issued"
  notice_id: string;
  application_id: string;
  specific_reasons: string[];
  within_30_days: boolean | null;
  body: string;
}

export interface CreditPolicyRow {
  id: string;
  product: string;
  min_credit_score: number;
  max_dti_ratio: number;
  min_annual_income: number;
  max_amount: number;
  base_apr: number;
  is_active: boolean;
  updated_at: string | null;
}

export interface PaymentScheduleRow {
  due_date: string;
  amount: number;
  principal: number;
  interest: number;
  status: string;                 // paid | due | scheduled | missed
}

export interface ServicedLoanRow {
  id: string;
  application_id: string | null;
  loan_number: string;
  product: string;
  borrower_name: string;
  principal: number;
  outstanding_principal: number;
  apr: number;
  term_months: number;
  monthly_payment: number;
  next_due_date: string | null;
  last_payment_date: string | null;
  last_payment_amount: number | null;
  payments_made: number;
  days_past_due: number;
  status: string;                 // CURRENT | DELINQUENT | DEFAULT | PAID_OFF
  delinquency_bucket: string;
  payment_schedule: PaymentScheduleRow[];
}

export interface ContactLogEntry {
  at: string;
  hour_local: number;
  channel: string;
  harassment: boolean;
  notes: string | null;
  actor: string | null;
}

export interface CollectionCaseRow {
  id: string;
  serviced_loan_id: string;
  loan_number: string | null;
  borrower_name: string | null;
  outstanding_principal: number | null;
  days_past_due: number | null;
  status: string;                 // OPEN | IN_PROGRESS | RESOLVED | ESCALATED
  delinquency_bucket: string;
  validation_notice_sent: boolean;
  validation_notice_sent_at: string | null;
  opened_at: string | null;
  last_contact_at: string | null;
  contact_log: ContactLogEntry[];
}

export interface DelinquenciesPayload {
  cases: CollectionCaseRow[];
  buckets: { label: string; value: number }[];
}

export interface CollectionContactResult {
  status: string;                 // "success" | PENDING_HITL | BLOCKED_* | ESCALATED_DEBATE
  case_id: string;
  contact_log?: ContactLogEntry[];
  rationale?: string | null;
  execution_id?: string;
  reason?: string;
  violations?: { framework: string; reason: string }[];
  blocking?: { framework: string; findings?: { message: string }[] }[];
}

const q = (status?: string) => (status ? `?status=${encodeURIComponent(status)}` : '');

export const lendingApi = {
  // /dashboard returns the analytics shape (status mix, approval rate, book value,
  // fair-lending four-fifths). There is no separate /analytics route on lending.
  getLendingDashboard: () => request<DomainAnalyticsPayload>('/lending/dashboard'),

  getLendingApplications: (status?: string) =>
    request<LoanApplicationRow[]>(`/lending/applications${q(status)}`),
  getLendingApplication: (id: string) =>
    request<LoanApplicationRow>(`/lending/applications/${id}`),
  createLendingApplication: (body: Record<string, any>) =>
    request<LoanApplicationRow>('/lending/applications', { method: 'POST', body: JSON.stringify(body) }),

  // Runs the deterministic credit policy through the 7-gate pipeline (ECOA +
  // FAIR_LENDING + TILA). A below-floor decision routes to HITL; a blocking gate
  // fails closed (422).
  underwriteApplication: (id: string, body?: { approval_cohorts?: Record<string, any>; business_necessity?: string }) =>
    request<UnderwriteResult>(`/lending/applications/${id}/underwrite`, {
      method: 'POST', body: JSON.stringify(body || {}),
    }),

  // Issues the Reg B adverse-action notice for a denial (only after a denial is on file).
  issueAdverseAction: (id: string) =>
    request<AdverseActionResult>(`/lending/applications/${id}/adverse-action`, { method: 'POST' }),
  getAdverseActions: () => request<AdverseActionRow[]>('/lending/adverse-action'),

  // Credit policy — the thresholds that drive every automated underwriting
  // decision. PUT is admin-gated on the backend.
  getCreditPolicies: () => request<CreditPolicyRow[]>('/lending/credit-policies'),
  putCreditPolicy: (product: string, body: {
    min_credit_score: number; max_dti_ratio: number; min_annual_income: number;
    max_amount: number; base_apr: number; is_active?: boolean;
  }) => request<CreditPolicyRow>(`/lending/credit-policies/${encodeURIComponent(product)}`, {
    method: 'PUT', body: JSON.stringify(body),
  }),

  // Loan servicing + collections. A collection contact is gated fail-closed
  // by FDCPA (contact-hour window, harassment flag, validation-notice timing);
  // a blocked attempt returns status BLOCKED_COMPLIANCE with `violations` and
  // is never logged to the case's contact history.
  getServicedLoans: () => request<ServicedLoanRow[]>('/lending/serviced-loans'),
  getDelinquencies: () => request<DelinquenciesPayload>('/lending/delinquencies'),
  attemptCollectionContact: (caseId: string, body: {
    hour_local: number; channel?: string; harassment?: boolean; notes?: string;
  }) => request<CollectionContactResult>(`/lending/collection-cases/${caseId}/contact`, {
    method: 'POST', body: JSON.stringify(body),
  }),
};
