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
};
