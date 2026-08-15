import { request } from '../http';

/* ─── Response / body shapes (bound to app/hr/api/v1/router.py) ─────────────
 * Own module, not merged into `api` (departments.ts is shared/contended) -
 * import `hrApi` directly, same pattern as healthcareApi/HealthcareView. */

export interface BenefitPlanRow {
  id: string; name: string; provider: string; benefit_type: string;
  description: string | null;
  employee_cost_individual: number; employee_cost_family: number; employer_contribution: number;
}

export interface BenefitEnrollmentRow {
  id: string; employee_id: string; plan_id: string; status: string;
  coverage_level: string; effective_date: string | null; agent_verified: boolean;
}

export interface CompensationRow {
  id: string; employee_id: string; comp_type: string; base_amount: number; currency: string;
  target_bonus_pct: number; equity_grant: number; equity_type: string | null;
  vesting_schedule: string | null; effective_date: string | null; is_current: boolean;
  change_reason: string | null;
}

export interface BoardingPlanRow {
  id: string; employee_id: string; plan_type: string; status: string;
  total_tasks: number; completed_tasks: number;
  start_date: string | null; target_completion_date: string | null;
}

export interface BoardingTaskRow {
  id: string; plan_id: string; title: string; description: string | null;
  assignee_id: string | null; status: string; due_date: string | null;
  is_automated: boolean; automation_result: Record<string, any> | null; completed_at: string | null;
}

export interface CourseRow {
  id: string; title: string; description: string | null; provider: string | null;
  is_required_for_compliance: boolean; estimated_minutes: number; status: string;
}

export interface CourseEnrollmentRow {
  id: string; employee_id: string; course_id: string; status: string;
  progress_pct: number; due_date: string | null; completed_at: string | null;
}

export interface ERCaseRow {
  id: string; title: string; category: string; status: string; severity: string;
  reporter_id: string | null; accused_id: string | null; investigator_id: string | null;
  ai_risk_assessment: string | null; ai_recommended_actions: string[]; opened_at: string | null;
}

export interface HeadcountPlanRow {
  id: string; name: string; department_id: string | null; target_year: number;
  budget_allocated: number; currency: string; status: string;
  planned_positions: { title: string; count: number; target_qtr?: string; est_salary?: number }[];
}

export interface PayrollRunRow {
  id: string; period_start: string | null; period_end: string | null; pay_date: string | null;
  status: string; total_gross: number; total_net: number; total_taxes: number;
  total_deductions: number; ai_anomalies_detected: any[];
}

export interface PayslipRow {
  id: string; run_id: string; employee_id: string; gross_pay: number; net_pay: number;
  taxes: Record<string, any>; deductions: Record<string, any>; created_at: string | null;
}

export interface ComplianceReportRow {
  id: string; framework: string; report_name: string; period_year: number; status: string;
  data: Record<string, any>; generated_at: string | null; submitted_at: string | null;
}

export interface ComplianceViolationRow {
  id: string; framework: string; severity: string; description: string;
  resolved: boolean; resolution_notes: string | null; created_at: string | null;
}

export interface HRMetricSnapshotRow {
  id: string; snapshot_date: string | null; total_headcount: number; active_contractors: number;
  voluntary_turnover_ytd: number | null; involuntary_turnover_ytd: number | null;
  open_requisitions: number; time_to_fill_avg_days: number | null;
  offer_acceptance_rate: number | null; diversity_metrics: Record<string, any>;
  total_payroll_run_rate: number | null;
}

export interface InterviewRow {
  id: string; candidate_id: string; interviewer_id: string; scheduled_at: string | null;
  duration_mins: number; interview_type: string; feedback_submitted: boolean;
  score: number | null; recommendation: string | null; notes: string | null;
}

export interface EmployeeDocumentRow {
  id: string; employee_id: string; doc_type: string; title: string; is_signed: boolean;
  signature_date: string | null; expiration_date: string | null; uploaded_at: string | null;
}

export interface TimesheetRow {
  id: string; employee_id: string; period_start: string | null; period_end: string | null;
  total_regular_hours: number; total_overtime_hours: number; status: string;
}

export interface ReviewCycleRow {
  id: string; name: string; start_date: string | null; end_date: string | null; is_active: boolean;
}

const q = (params: Record<string, string | undefined>) => {
  const s = new URLSearchParams(Object.entries(params).filter(([, v]) => !!v) as [string, string][]).toString();
  return s ? `?${s}` : '';
};

export const hrApi = {
  // ── Benefits ──
  getBenefitPlans: () => request<BenefitPlanRow[]>('/hr/benefit-plans'),
  createBenefitPlan: (body: { name: string; provider: string; benefit_type: string; description?: string;
    employee_cost_individual?: number; employee_cost_family?: number; employer_contribution?: number }) =>
    request<{ id: string; name: string }>('/hr/benefit-plans', { method: 'POST', body: JSON.stringify(body) }),
  getBenefitEnrollments: (employeeId?: string) =>
    request<BenefitEnrollmentRow[]>(`/hr/benefit-enrollments${q({ employee_id: employeeId })}`),
  createBenefitEnrollment: (body: { employee_id: string; plan_id: string; coverage_level?: string;
    effective_date: string; covered_dependents?: string[] }) =>
    request<{ id: string; status: string }>('/hr/benefit-enrollments', { method: 'POST', body: JSON.stringify(body) }),
  verifyBenefitEnrollment: (id: string) =>
    request<{ enrollment_id: string; verified: boolean; status: string }>(
      `/hr/benefit-enrollments/${id}/verify`, { method: 'POST' }),

  // ── Compensation ──
  getCompensation: (employeeId?: string) =>
    request<CompensationRow[]>(`/hr/compensation${q({ employee_id: employeeId })}`),
  createCompensation: (body: { employee_id: string; comp_type?: string; base_amount: number; currency?: string;
    target_bonus_pct?: number; equity_grant?: number; equity_type?: string; vesting_schedule?: string;
    effective_date: string; change_reason?: string }) =>
    request<{ id: string; base_amount: number }>('/hr/compensation', { method: 'POST', body: JSON.stringify(body) }),
  compensationMarketAnalysis: (id: string) =>
    request<{ compensation_id: string; analysis: any }>(`/hr/compensation/${id}/market-analysis`, { method: 'POST' }),

  // ── Onboarding / Offboarding ──
  getBoardingPlans: (employeeId?: string) =>
    request<BoardingPlanRow[]>(`/hr/boarding-plans${q({ employee_id: employeeId })}`),
  createBoardingPlan: (body: { employee_id: string; plan_type?: string; start_date: string;
    target_completion_date?: string; tasks?: string[] }) =>
    request<{ id: string; total_tasks: number }>('/hr/boarding-plans', { method: 'POST', body: JSON.stringify(body) }),
  getBoardingTasks: (planId?: string) =>
    request<BoardingTaskRow[]>(`/hr/boarding-tasks${q({ plan_id: planId })}`),
  transitionBoardingTask: (id: string, to_state: string) =>
    request<any>(`/hr/boarding-tasks/${id}/transition`, { method: 'POST', body: JSON.stringify({ to_state }) }),
  onboardingCheckin: (employeeId: string, weekNum: number, response = '') =>
    request<any>(`/hr/employees/${employeeId}/onboarding-checkin`, {
      method: 'POST', body: JSON.stringify({ week_num: weekNum, response }) }),
  offboardingExitInterview: (employeeId: string, surveyResponses: Record<string, string>) =>
    request<{ employee_id: string; boarding_plan_id: string; task_id: string; analysis: any }>(
      `/hr/employees/${employeeId}/offboarding-exit-interview`,
      { method: 'POST', body: JSON.stringify({ survey_responses: surveyResponses }) }),

  // ── Learning ──
  getCourses: () => request<CourseRow[]>('/hr/courses'),
  createCourse: (body: { title: string; description?: string; provider?: string;
    is_required_for_compliance?: boolean; estimated_minutes?: number }) =>
    request<{ id: string; title: string }>('/hr/courses', { method: 'POST', body: JSON.stringify(body) }),
  getCourseEnrollments: (employeeId?: string) =>
    request<CourseEnrollmentRow[]>(`/hr/course-enrollments${q({ employee_id: employeeId })}`),
  createCourseEnrollment: (body: { employee_id: string; course_id: string; due_date?: string }) =>
    request<{ id: string; status: string }>('/hr/course-enrollments', { method: 'POST', body: JSON.stringify(body) }),
  transitionCourseEnrollment: (id: string, to_state: string) =>
    request<any>(`/hr/course-enrollments/${id}/transition`, { method: 'POST', body: JSON.stringify({ to_state }) }),

  // ── Employee Relations ──
  getERCases: () => request<ERCaseRow[]>('/hr/er-cases'),
  createERCase: (body: { title: string; description: string; reporter_id?: string; accused_id?: string;
    category: string; severity?: string }) =>
    request<{ id: string; status: string }>('/hr/er-cases', { method: 'POST', body: JSON.stringify(body) }),
  transitionERCase: (id: string, to_state: string) =>
    request<any>(`/hr/er-cases/${id}/transition`, { method: 'POST', body: JSON.stringify({ to_state }) }),
  triageERCase: (id: string) => request<any>(`/hr/er-cases/${id}/triage`, { method: 'POST' }),

  // ── Workforce Planning ──
  getHeadcountPlans: () => request<HeadcountPlanRow[]>('/hr/headcount-plans'),
  createHeadcountPlan: (body: { name: string; department_id?: string; target_year: number;
    budget_allocated?: number; currency?: string;
    planned_positions?: { title: string; count: number; target_qtr?: string; est_salary?: number }[] }) =>
    request<{ id: string; status: string }>('/hr/headcount-plans', { method: 'POST', body: JSON.stringify(body) }),
  transitionHeadcountPlan: (id: string, to_state: string) =>
    request<any>(`/hr/headcount-plans/${id}/transition`, { method: 'POST', body: JSON.stringify({ to_state }) }),

  // ── Payroll ──
  getPayrollRuns: () => request<PayrollRunRow[]>('/hr/payroll-runs'),
  createPayrollRun: (body: { period_start: string; period_end: string; pay_date: string }) =>
    request<{ id: string; status: string }>('/hr/payroll-runs', { method: 'POST', body: JSON.stringify(body) }),
  transitionPayrollRun: (id: string, to_state: string) =>
    request<any>(`/hr/payroll-runs/${id}/transition`, { method: 'POST', body: JSON.stringify({ to_state }) }),
  generatePayslips: (runId: string) =>
    request<{ run_id: string; created: number; skipped_no_compensation: number; skipped_existing: number }>(
      `/hr/payroll-runs/${runId}/generate-payslips`, { method: 'POST' }),
  getPayslips: (runId?: string, employeeId?: string) =>
    request<PayslipRow[]>(`/hr/payslips${q({ run_id: runId, employee_id: employeeId })}`),

  // ── Compliance ──
  getComplianceReports: () => request<ComplianceReportRow[]>('/hr/compliance-reports'),
  createComplianceReport: (body: { framework: string; report_name: string; period_year: number;
    data?: Record<string, any> }) =>
    request<{ id: string; framework: string }>('/hr/compliance-reports', { method: 'POST', body: JSON.stringify(body) }),
  generateEeocReport: () =>
    request<{ id: string; passed: boolean; flagged: string[]; decided_total: number }>(
      '/hr/compliance-reports/eeoc/generate', { method: 'POST' }),
  getComplianceViolations: (resolved?: boolean) =>
    request<ComplianceViolationRow[]>(`/hr/compliance-violations${resolved === undefined ? '' : `?resolved=${resolved}`}`),
  resolveComplianceViolation: (id: string, resolutionNotes: string) =>
    request<{ id: string; resolved: boolean }>(`/hr/compliance-violations/${id}/resolve`, {
      method: 'POST', body: JSON.stringify({ resolution_notes: resolutionNotes }) }),

  // ── Analytics Snapshots ──
  getHRMetrics: (days = 180) => request<HRMetricSnapshotRow[]>(`/hr/hr-metrics?days=${days}`),
  generateHRMetricSnapshot: () =>
    request<{ id: string; snapshot_date: string; total_headcount: number }>(
      '/hr/hr-metrics/snapshot', { method: 'POST' }),

  // ── Interviews ──
  getInterviews: (candidateId?: string) =>
    request<InterviewRow[]>(`/hr/interviews${q({ candidate_id: candidateId })}`),
  scheduleInterview: (body: { candidate_id: string; interviewer_id: string; scheduled_at: string;
    duration_mins?: number; interview_type: string }) =>
    request<{ id: string; scheduled_at: string }>('/hr/interviews', { method: 'POST', body: JSON.stringify(body) }),
  submitInterviewFeedback: (id: string, body: { score: number; recommendation: string; notes?: string }) =>
    request<{ id: string; feedback_submitted: boolean; recommendation: string }>(
      `/hr/interviews/${id}/feedback`, { method: 'POST', body: JSON.stringify(body) }),

  // ── Employee Documents ──
  getEmployeeDocuments: (employeeId?: string) =>
    request<EmployeeDocumentRow[]>(`/hr/employee-documents${q({ employee_id: employeeId })}`),
  createEmployeeDocument: (body: { employee_id: string; doc_type: string; title: string; file_path: string;
    is_pii?: boolean; expiration_date?: string }) =>
    request<{ id: string; title: string }>('/hr/employee-documents', { method: 'POST', body: JSON.stringify(body) }),
  signEmployeeDocument: (id: string) =>
    request<{ id: string; is_signed: boolean }>(`/hr/employee-documents/${id}/sign`, { method: 'POST' }),

  // ── Timesheets ──
  getTimesheets: (employeeId?: string) =>
    request<TimesheetRow[]>(`/hr/timesheets${q({ employee_id: employeeId })}`),
  createTimesheet: (body: { employee_id: string; period_start: string; period_end: string;
    total_regular_hours?: number; total_overtime_hours?: number }) =>
    request<{ id: string; status: string }>('/hr/timesheets', { method: 'POST', body: JSON.stringify(body) }),
  transitionTimesheet: (id: string, to_state: string) =>
    request<any>(`/hr/timesheets/${id}/transition`, { method: 'POST', body: JSON.stringify({ to_state }) }),

  // ── Performance ──
  getPerformanceCycles: () => request<ReviewCycleRow[]>('/hr/performance-cycles'),
  createPerformanceCycle: (body: { name: string; start_date: string; end_date: string }) =>
    request<{ id: string; name: string }>('/hr/performance-cycles', { method: 'POST', body: JSON.stringify(body) }),
  createPerformanceReview: (body: { cycle_id: string; employee_id: string; reviewer_id: string }) =>
    request<{ id: string; status: string }>('/hr/performance-reviews', { method: 'POST', body: JSON.stringify(body) }),
  transitionPerformanceReview: (id: string, to_state: string) =>
    request<any>(`/hr/performance-reviews/${id}/transition`, { method: 'POST', body: JSON.stringify({ to_state }) }),
  submitSelfRating: (id: string, rating: number, assessment: string) =>
    request<{ id: string; status: string }>(`/hr/performance-reviews/${id}/self-rating`, {
      method: 'POST', body: JSON.stringify({ rating, assessment }) }),
  submitManagerRating: (id: string, rating: number, assessment: string) =>
    request<{ id: string; status: string }>(`/hr/performance-reviews/${id}/manager-rating`, {
      method: 'POST', body: JSON.stringify({ rating, assessment }) }),
  synthesizeReviewFeedback: (id: string, rawFeedback: string[]) =>
    request<{ review_id: string; analysis: any }>(`/hr/performance-reviews/${id}/synthesize-feedback`, {
      method: 'POST', body: JSON.stringify({ raw_feedback: rawFeedback }) }),

  // ── Requisition fairness sweep (EEOC four-fifths, real statistical audit) ──
  runRequisitionFairnessSweep: (requisitionId: string) =>
    request<{ requisition_id: string; status: string; execution_id: string | null;
      flagged_attributes: string[] | null; decided_total: number | null; reason?: string }>(
      `/hr/requisitions/${requisitionId}/fairness-sweep`, { method: 'POST' }),

  // ── BambooHR connector ──
  syncBambooHR: (subdomain: string, apiKey: string) =>
    request<{ ok: boolean; fetched?: number; created: number; updated: number; skipped?: number }>(
      '/hr/connectors/bamboohr/sync', { method: 'POST', body: JSON.stringify({ subdomain, api_key: apiKey }) }),
};
