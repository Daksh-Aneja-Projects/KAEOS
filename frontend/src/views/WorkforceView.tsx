import React, { useEffect, useId, useState } from 'react';
import {
  Users, Briefcase, Calendar, Star, Search, UserPlus, Clock,
  CheckCircle2, XCircle, ArrowUpRight, BarChart3,
  MapPin, TrendingUp, RefreshCw,
  Zap, ExternalLink, ShieldAlert, Loader2,
  Heart, DollarSign, LogIn, LogOut, GraduationCap, Scale, LineChart,
  Wallet, ShieldCheck, FileText, PenLine, Link2, Plus, X, Gauge, Sparkles,
} from 'lucide-react';
import { api } from '../api/client';
import type { WorkflowSpec } from '../api/client';
import { hrApi } from '../api/endpoints/hr';
import type {
  BenefitPlanRow, BenefitEnrollmentRow, CompensationRow, BoardingPlanRow, BoardingTaskRow,
  CourseRow, CourseEnrollmentRow, ERCaseRow, HeadcountPlanRow, PayrollRunRow, PayslipRow,
  ComplianceReportRow, ComplianceViolationRow, HRMetricSnapshotRow, InterviewRow,
  EmployeeDocumentRow, TimesheetRow, ReviewCycleRow,
} from '../api/endpoints/hr';
import { useTheme } from '../context/ThemeContext';
import { humanize, formatDate } from '../lib/format';
import { PAGE_PAD } from '../lib/layout';
import DomainAnalytics from '../components/DomainAnalytics';
import WorkflowActions from '../components/WorkflowActions';
import CreateEntityModal from '../components/CreateEntityModal';
import BulkActionBar from '../components/BulkActionBar';
import { useBulkSelect } from '../hooks/useBulkSelect';
import GateTrace from '../components/GateTrace';
import TableCard from '../components/shared/TableCard';
import StatCard from '../components/shared/StatCard';
import { MiniDonut } from '../components/shared/MiniDonut';
import { useFocusTrap } from '../hooks/useFocusTrap';
import { announce } from '../components/a11y/LiveRegion';

// Types defined locally to avoid Vite ESM dev-mode import type resolution issues
interface HREmployee {
  id: string;
  first_name: string;
  last_name: string;
  email?: string;
  status: string;
  job_title?: string;
  location?: string;
  hire_date?: string;
}

interface HRRequisition {
  id: string;
  title: string;
  department?: string;
  status: string;
  headcount?: number;
  target_salary_min?: number;
  target_salary_max?: number;
}

interface HRCandidate {
  id: string;
  name: string;
  email?: string;
  stage: string;
  ai_score: number | null;
  ai_summary?: string | null;
  ai_red_flags?: string[];
  requisition_id?: string;
}

interface HRTimeOffRequest {
  id: string;
  employee_id: string;
  status: string;
  leave_type: string;
  start_date?: string;
  end_date?: string;
  hours_requested?: number;
}

interface HRPerformanceReview {
  id: string;
  employee_id: string;
  status: string;
  manager_rating: number | null;
  self_rating?: number | null;
  cycle_id?: string;
}

type HRTab =
  | 'directory' | 'recruiting' | 'time' | 'performance'
  | 'benefits' | 'compensation' | 'onboarding' | 'learning'
  | 'er' | 'payroll' | 'planning' | 'compliance' | 'analytics';

const ALL_TABS: HRTab[] = [
  'directory', 'recruiting', 'time', 'performance', 'benefits', 'compensation',
  'onboarding', 'learning', 'er', 'payroll', 'planning', 'compliance', 'analytics',
];

// ── Field-list modal shared by every "create" / "agent action" flow below.
// Mirrors CreateEntityModal's look but calls a caller-supplied submit handler
// directly (the typed hrApi wrappers), since most of these bodies (dates,
// selects keyed off loaded rows, free-text survey answers) don't fit the
// generic flat-POST shape CreateEntityModal targets.
type QField = {
  key: string; label: string; type: 'text' | 'number' | 'date' | 'textarea' | 'select';
  options?: { value: string; label: string }[]; required?: boolean; placeholder?: string; defaultValue?: string;
};

const QuickModal: React.FC<{
  open: boolean; title: string; submitLabel: string; icon: React.ElementType; fields: QField[];
  onClose: () => void; onSubmit: (values: Record<string, string>) => Promise<void>;
}> = ({ open, title, submitLabel, icon: Icon, fields, onClose, onSubmit }) => {
  const { colors } = useTheme();
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const titleId = useId();
  const trapRef = useFocusTrap<HTMLDivElement>(open, onClose);

  useEffect(() => { if (open) { setValues({}); setError(''); } }, [open]);

  if (!open) return null;

  const val = (f: QField) => values[f.key] ?? f.defaultValue ?? '';
  const set = (k: string, v: string) => setValues(p => ({ ...p, [k]: v }));

  const submit = async () => {
    for (const f of fields) {
      if (f.required && !val(f).trim()) {
        const msg = `${f.label} is required`;
        setError(msg);
        announce(msg, 'assertive');
        return;
      }
    }
    setBusy(true); setError('');
    try {
      await onSubmit(values);
    } catch (e: any) {
      const msg = e?.message || 'Action failed';
      setError(msg);
      announce(msg, 'assertive');
    } finally {
      setBusy(false);
    }
  };

  const inputStyle = { background: colors.canvas, border: `1px solid ${colors.hairline}`, color: colors.ink } as React.CSSProperties;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ background: 'rgba(0,0,0,0.55)' }}
      onClick={onClose}>
      <div ref={trapRef} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}
        className="w-full max-w-md rounded-2xl p-5 space-y-4 max-h-[85vh] overflow-y-auto"
        style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}
        onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <h2 id={titleId} className="text-[15px] font-bold flex items-center gap-2" style={{ color: colors.ink }}>
            <Icon className="w-4 h-4" style={{ color: colors.primary }} />{title}
          </h2>
          <button onClick={onClose} aria-label="Close dialog" className="p-1 rounded" style={{ color: colors.inkSubtle }}>
            <X className="w-4 h-4" />
          </button>
        </div>

        {fields.map(f => {
          const fieldId = `${titleId}-${f.key}`;
          return (
            <div key={f.key}>
              <label htmlFor={fieldId} className="text-[11px] font-semibold block mb-1" style={{ color: colors.inkSubtle }}>
                {f.label}{f.required && <span style={{ color: colors.error }}> *</span>}
              </label>
              {f.type === 'textarea' ? (
                <textarea id={fieldId} value={val(f)} onChange={e => set(f.key, e.target.value)} rows={3}
                  placeholder={f.placeholder}
                  className="w-full px-3 py-2 rounded-lg text-[12px] focus:outline-none resize-none" style={inputStyle} />
              ) : f.type === 'select' ? (
                <select id={fieldId} value={val(f)} onChange={e => set(f.key, e.target.value)}
                  className="w-full px-3 py-2 rounded-lg text-[12px] focus:outline-none" style={inputStyle}>
                  <option value="">Select…</option>
                  {(f.options || []).map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              ) : (
                <input id={fieldId} type={f.type} value={val(f)} onChange={e => set(f.key, e.target.value)}
                  placeholder={f.placeholder}
                  className="w-full px-3 py-2 rounded-lg text-[12px] focus:outline-none" style={inputStyle} />
              )}
            </div>
          );
        })}

        {error && <p role="alert" className="text-[11px] font-medium" style={{ color: colors.error }}>{error}</p>}

        <div className="flex justify-end gap-2 pt-1">
          <button onClick={onClose} className="px-3 py-2 rounded-lg text-[12px] font-semibold"
            style={{ background: 'transparent', color: colors.inkSubtle }}>Cancel</button>
          <button onClick={submit} disabled={busy}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-[12px] font-semibold disabled:opacity-50 text-white"
            style={{ background: colors.primary }}>
            {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Icon className="w-3.5 h-3.5" />}
            {submitLabel}
          </button>
        </div>
      </div>
    </div>
  );
};

// Every kind of create/agent-action modal on this page, dispatched from one
// QuickModal instance (config in, typed hrApi call out) - keeps 20+ small
// forms from becoming 20+ near-identical modal blocks.
type ModalKind =
  | 'benefit-plan' | 'benefit-enrollment' | 'compensation'
  | 'boarding-plan' | 'onboarding-checkin' | 'exit-interview'
  | 'course' | 'course-enrollment'
  | 'er-case' | 'headcount-plan' | 'payroll-run'
  | 'compliance-report' | 'resolve-violation'
  | 'interview' | 'interview-feedback'
  | 'employee-document' | 'timesheet'
  | 'review-cycle' | 'performance-review' | 'self-rating' | 'manager-rating' | 'synthesize-feedback'
  | 'bamboohr-connect';

interface ModalCtx { kind: ModalKind; id?: string; label?: string; }

const WorkforceView: React.FC<{ domain?: string; defaultTab?: string }> = ({ defaultTab }) => {
  const { colors } = useTheme();
  const [tab, setTab] = useState<HRTab>(() => {
    if (defaultTab && (ALL_TABS as string[]).includes(defaultTab)) return defaultTab as HRTab;
    if (defaultTab === 'employees') return 'directory';
    return 'directory';
  });
  const [loading, setLoading] = useState(true);

  // Core data state
  const [employees, setEmployees] = useState<HREmployee[]>([]);
  const [requisitions, setRequisitions] = useState<HRRequisition[]>([]);
  const [candidates, setCandidates] = useState<HRCandidate[]>([]);
  const [timeOff, setTimeOff] = useState<HRTimeOffRequest[]>([]);
  const [reviews, setReviews] = useState<HRPerformanceReview[]>([]);
  const [reviewCycles, setReviewCycles] = useState<ReviewCycleRow[]>([]);
  const [workflows, setWorkflows] = useState<Record<string, WorkflowSpec>>({});

  // Newly-covered schema state
  const [benefitPlans, setBenefitPlans] = useState<BenefitPlanRow[]>([]);
  const [benefitEnrollments, setBenefitEnrollments] = useState<BenefitEnrollmentRow[]>([]);
  const [compensation, setCompensation] = useState<CompensationRow[]>([]);
  const [boardingPlans, setBoardingPlans] = useState<BoardingPlanRow[]>([]);
  const [boardingTasks, setBoardingTasks] = useState<BoardingTaskRow[]>([]);
  const [courses, setCourses] = useState<CourseRow[]>([]);
  const [courseEnrollments, setCourseEnrollments] = useState<CourseEnrollmentRow[]>([]);
  const [erCases, setErCases] = useState<ERCaseRow[]>([]);
  const [headcountPlans, setHeadcountPlans] = useState<HeadcountPlanRow[]>([]);
  const [payrollRuns, setPayrollRuns] = useState<PayrollRunRow[]>([]);
  const [payslips, setPayslips] = useState<PayslipRow[]>([]);
  const [complianceReports, setComplianceReports] = useState<ComplianceReportRow[]>([]);
  const [complianceViolations, setComplianceViolations] = useState<ComplianceViolationRow[]>([]);
  const [hrMetrics, setHrMetrics] = useState<HRMetricSnapshotRow[]>([]);
  const [interviews, setInterviews] = useState<InterviewRow[]>([]);
  const [employeeDocuments, setEmployeeDocuments] = useState<EmployeeDocumentRow[]>([]);
  const [timesheets, setTimesheets] = useState<TimesheetRow[]>([]);

  const [createOpen, setCreateOpen] = useState(false);
  const [createKind, setCreateKind] = useState<'requisition' | 'candidate' | null>(null);
  const [modalCtx, setModalCtx] = useState<ModalCtx | null>(null);
  const bulk = useBulkSelect(timeOff, workflows['time_off_request'], t => t.status);

  // Filters
  const [searchQ, setSearchQ] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');

  // Recruiting action state (gated screening + stage advance)
  const [screeningId, setScreeningId] = useState<string | null>(null);
  const [trace, setTrace] = useState<{ id: string; label: string; result?: any } | null>(null);
  const [advancingId, setAdvancingId] = useState<string | null>(null);
  const [provenance, setProvenance] = useState<Record<string, string>>({});
  const [actionMsg, setActionMsg] = useState<string>('');
  const [busyId, setBusyId] = useState<string | null>(null);

  // Backend CandidateStage enum forward order (matches app/hr/models/recruiting.py)
  const CANDIDATE_STAGES = [
    'APPLIED', 'AI_SCREENING', 'RECRUITER_SCREEN', 'HM_INTERVIEW',
    'PANEL_INTERVIEW', 'OFFER_PREP', 'OFFER_EXTENDED', 'HIRED',
  ];

  const nextStage = (stage: string): string | null => {
    const i = CANDIDATE_STAGES.indexOf(stage);
    return i >= 0 && i < CANDIDATE_STAGES.length - 1 ? CANDIDATE_STAGES[i + 1] : null;
  };

  // Human-readable name resolution - never surface a raw id to the user.
  const employeeName = (id?: string | null): string => {
    if (!id) return 'Unassigned';
    const e = employees.find(x => x.id === id);
    return e ? `${e.first_name} ${e.last_name}` : `${id.slice(0, 8)}…`;
  };
  const candidateName = (id?: string | null): string => {
    if (!id) return 'Unknown candidate';
    const c = candidates.find(x => x.id === id);
    return c ? c.name : `${id.slice(0, 8)}…`;
  };
  const planName = (id?: string | null): string => {
    const p = benefitPlans.find(x => x.id === id);
    return p ? p.name : (id ? `${id.slice(0, 8)}…` : '-');
  };
  const courseName = (id?: string | null): string => {
    const c = courses.find(x => x.id === id);
    return c ? c.title : (id ? `${id.slice(0, 8)}…` : '-');
  };
  const boardingPlanOwner = (planId?: string | null): string => {
    const p = boardingPlans.find(x => x.id === planId);
    return p ? employeeName(p.employee_id) : 'Unknown';
  };
  const runPeriodLabel = (runId?: string | null): string => {
    const r = payrollRuns.find(x => x.id === runId);
    return r ? `${formatDate(r.period_start)} - ${formatDate(r.period_end)}` : (runId ? `${runId.slice(0, 8)}…` : '-');
  };

  const loadData = async () => {
    setLoading(true);
    const results = await Promise.allSettled([
      api.getHREmployees(), api.getHRRequisitions(), api.getHRCandidates(),
      api.getHRTimeOffRequests(), api.getHRPerformanceReviews(), api.getDomainWorkflows('hr'),
      hrApi.getBenefitPlans(), hrApi.getBenefitEnrollments(),
      hrApi.getCompensation(),
      hrApi.getBoardingPlans(), hrApi.getBoardingTasks(),
      hrApi.getCourses(), hrApi.getCourseEnrollments(),
      hrApi.getERCases(),
      hrApi.getHeadcountPlans(),
      hrApi.getPayrollRuns(), hrApi.getPayslips(),
      hrApi.getComplianceReports(), hrApi.getComplianceViolations(),
      hrApi.getHRMetrics(),
      hrApi.getInterviews(),
      hrApi.getEmployeeDocuments(),
      hrApi.getTimesheets(),
      hrApi.getPerformanceCycles(),
    ]);
    const val = (i: number, d: any) => (results[i].status === 'fulfilled' ? (results[i] as any).value ?? d : d);
    setEmployees(val(0, [])); setRequisitions(val(1, [])); setCandidates(val(2, []));
    setTimeOff(val(3, [])); setReviews(val(4, [])); setWorkflows(val(5, {}));
    setBenefitPlans(val(6, [])); setBenefitEnrollments(val(7, []));
    setCompensation(val(8, []));
    setBoardingPlans(val(9, [])); setBoardingTasks(val(10, []));
    setCourses(val(11, [])); setCourseEnrollments(val(12, []));
    setErCases(val(13, []));
    setHeadcountPlans(val(14, []));
    setPayrollRuns(val(15, [])); setPayslips(val(16, []));
    setComplianceReports(val(17, [])); setComplianceViolations(val(18, []));
    setHrMetrics(val(19, []));
    setInterviews(val(20, []));
    setEmployeeDocuments(val(21, []));
    setTimesheets(val(22, []));
    setReviewCycles(val(23, []));
    setLoading(false);
  };

  const handleScreen = async (candidateId: string) => {
    setScreeningId(candidateId);
    setActionMsg('');
    setTrace({ id: candidateId, label: 'Candidate screening', result: undefined });
    try {
      const res = await api.screenHRCandidate(candidateId);
      setTrace({ id: candidateId, label: 'Candidate screening', result: res });
      const execId = res?.provenance?.execution_id;
      if (execId) setProvenance(prev => ({ ...prev, [candidateId]: execId }));
      setActionMsg(res?.screening === 'gated'
        ? `Screening gated (${humanize(res.status)}) - routed for human review.`
        : 'AI screening complete.');
      await loadData();
    } catch (e: any) {
      setActionMsg(`Screening failed: ${e?.message || e}`);
      setTrace(null);
    } finally {
      setScreeningId(null);
    }
  };

  const handleAdvance = async (candidateId: string, target: string) => {
    setAdvancingId(candidateId);
    setActionMsg('');
    try {
      await api.advanceHRCandidate(candidateId, target);
      await loadData();
    } catch (e: any) {
      setActionMsg(`Advance failed: ${e?.message || e}`);
    } finally {
      setAdvancingId(null);
    }
  };

  const handleFairnessSweep = async (requisitionId: string) => {
    setBusyId(`sweep-${requisitionId}`);
    setActionMsg('');
    try {
      const res = await hrApi.runRequisitionFairnessSweep(requisitionId);
      if (res.status === 'INSUFFICIENT_GROUPS') {
        setActionMsg(`Fairness sweep: not enough self-ID data yet (${res.decided_total ?? 0} decided candidates) - advisory only.`);
      } else if (res.status === 'PENDING_HITL') {
        setActionMsg(`Fairness sweep flagged adverse impact on ${(res.flagged_attributes || []).map(humanize).join(', ')} - routed to human review.`);
      } else {
        setActionMsg(`Fairness sweep complete: ${humanize(res.status)}.`);
      }
      await loadData();
    } catch (e: any) {
      setActionMsg(`Fairness sweep failed: ${e?.message || e}`);
    } finally {
      setBusyId(null);
    }
  };

  // Direct (no-input) agent/action buttons shared across several tabs.
  const runAction = async (key: string, fn: () => Promise<any>, successMsg: (r: any) => string) => {
    setBusyId(key);
    setActionMsg('');
    try {
      const res = await fn();
      setActionMsg(successMsg(res));
      await loadData();
    } catch (e: any) {
      setActionMsg(`Action failed: ${e?.message || e}`);
    } finally {
      setBusyId(null);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const openModal = (kind: ModalKind, id?: string, label?: string) => setModalCtx({ kind, id, label });
  const closeModal = () => setModalCtx(null);

  const handleModalSubmit = async (values: Record<string, string>) => {
    if (!modalCtx) return;
    const { kind, id } = modalCtx;
    switch (kind) {
      case 'benefit-plan':
        await hrApi.createBenefitPlan({
          name: values.name, provider: values.provider, benefit_type: values.benefit_type,
          description: values.description || undefined,
          employee_cost_individual: Number(values.employee_cost_individual || 0),
          employer_contribution: Number(values.employer_contribution || 0),
        });
        setActionMsg('Benefit plan created.');
        break;
      case 'benefit-enrollment':
        await hrApi.createBenefitEnrollment({
          employee_id: values.employee_id, plan_id: values.plan_id,
          coverage_level: values.coverage_level || 'INDIVIDUAL',
          effective_date: values.effective_date,
        });
        setActionMsg('Employee enrolled in benefit plan.');
        break;
      case 'compensation':
        await hrApi.createCompensation({
          employee_id: values.employee_id, base_amount: Number(values.base_amount),
          comp_type: values.comp_type || 'SALARY', effective_date: values.effective_date,
          change_reason: values.change_reason || undefined,
        });
        setActionMsg('Compensation record created.');
        break;
      case 'boarding-plan':
        await hrApi.createBoardingPlan({
          employee_id: values.employee_id, plan_type: values.plan_type || 'ONBOARDING',
          start_date: values.start_date,
          tasks: values.tasks ? values.tasks.split(',').map(t => t.trim()).filter(Boolean) : undefined,
        });
        setActionMsg('Boarding plan created.');
        break;
      case 'onboarding-checkin': {
        const res = await hrApi.onboardingCheckin(id!, Number(values.week_num), values.response || '');
        setActionMsg(res.status === 'NO_RESPONSE'
          ? 'Check-in logged: no response from the new hire yet.'
          : `Check-in complete (${humanize(res.status)}).`);
        break;
      }
      case 'exit-interview': {
        await hrApi.offboardingExitInterview(id!, {
          reason_for_leaving: values.reason_for_leaving || '',
          would_recommend: values.would_recommend || '',
          additional_comments: values.additional_comments || '',
        });
        setActionMsg('Exit interview analyzed and recorded on the offboarding plan.');
        break;
      }
      case 'course':
        await hrApi.createCourse({
          title: values.title, provider: values.provider || undefined,
          is_required_for_compliance: values.is_required_for_compliance === 'yes',
          estimated_minutes: Number(values.estimated_minutes || 60),
        });
        setActionMsg('Course created.');
        break;
      case 'course-enrollment':
        await hrApi.createCourseEnrollment({ employee_id: values.employee_id, course_id: values.course_id });
        setActionMsg('Employee enrolled in course.');
        break;
      case 'er-case':
        await hrApi.createERCase({
          title: values.title, description: values.description,
          reporter_id: values.reporter_id || undefined, accused_id: values.accused_id || undefined,
          category: values.category, severity: values.severity || 'MEDIUM',
        });
        setActionMsg('ER case opened.');
        break;
      case 'headcount-plan':
        await hrApi.createHeadcountPlan({
          name: values.name, department_id: values.department_id || undefined,
          target_year: Number(values.target_year), budget_allocated: Number(values.budget_allocated || 0),
          planned_positions: values.position_title
            ? [{ title: values.position_title, count: Number(values.position_count || 1) }] : [],
        });
        setActionMsg('Headcount plan created.');
        break;
      case 'payroll-run':
        await hrApi.createPayrollRun({
          period_start: values.period_start, period_end: values.period_end, pay_date: values.pay_date,
        });
        setActionMsg('Payroll run created.');
        break;
      case 'compliance-report':
        await hrApi.createComplianceReport({
          framework: values.framework, report_name: values.report_name,
          period_year: Number(values.period_year),
        });
        setActionMsg('Compliance report logged.');
        break;
      case 'resolve-violation':
        await hrApi.resolveComplianceViolation(id!, values.resolution_notes);
        setActionMsg('Violation marked resolved.');
        break;
      case 'interview':
        await hrApi.scheduleInterview({
          candidate_id: values.candidate_id, interviewer_id: values.interviewer_id,
          scheduled_at: values.scheduled_at, interview_type: values.interview_type,
        });
        setActionMsg('Interview scheduled.');
        break;
      case 'interview-feedback':
        await hrApi.submitInterviewFeedback(id!, {
          score: Number(values.score), recommendation: values.recommendation, notes: values.notes || undefined,
        });
        setActionMsg('Interview feedback submitted.');
        break;
      case 'employee-document':
        await hrApi.createEmployeeDocument({
          employee_id: values.employee_id, doc_type: values.doc_type, title: values.title,
          file_path: `documents/${values.employee_id}/${(values.doc_type || 'other').toLowerCase()}.pdf`,
        });
        setActionMsg('Document logged.');
        break;
      case 'timesheet':
        await hrApi.createTimesheet({
          employee_id: values.employee_id, period_start: values.period_start, period_end: values.period_end,
          total_regular_hours: Number(values.total_regular_hours || 40),
        });
        setActionMsg('Timesheet filed.');
        break;
      case 'review-cycle':
        await hrApi.createPerformanceCycle({
          name: values.name, start_date: values.start_date, end_date: values.end_date,
        });
        setActionMsg('Review cycle created.');
        break;
      case 'performance-review':
        await hrApi.createPerformanceReview({
          cycle_id: values.cycle_id, employee_id: values.employee_id, reviewer_id: values.reviewer_id,
        });
        setActionMsg('Performance review opened.');
        break;
      case 'self-rating':
        await hrApi.submitSelfRating(id!, Number(values.rating), values.assessment);
        setActionMsg('Self-assessment submitted.');
        break;
      case 'manager-rating':
        await hrApi.submitManagerRating(id!, Number(values.rating), values.assessment);
        setActionMsg('Manager rating submitted; review completed.');
        break;
      case 'synthesize-feedback': {
        const feedback = (values.raw_feedback || '').split('\n').map(s => s.trim()).filter(Boolean);
        await hrApi.synthesizeReviewFeedback(id!, feedback);
        setActionMsg('360 feedback synthesized by the Performance Agent.');
        break;
      }
      case 'bamboohr-connect': {
        const res = await hrApi.syncBambooHR(values.subdomain, values.api_key);
        setActionMsg(`BambooHR sync complete: ${res.created} created, ${res.updated} updated.`);
        break;
      }
    }
    announce('Done');
    closeModal();
    await loadData();
  };

  // ── Status color helper ──
  const statusColor = (s: string) => {
    const normalized = (s || '').toUpperCase();
    if (['ACTIVE', 'APPROVED', 'COMPLETED', 'HIRED', 'FILLED', 'RESOLVED', 'PROCESSED', 'CLOSED'].includes(normalized)) return colors.success;
    if (['PENDING', 'REQUESTED', 'DRAFT', 'ONBOARDING', 'IN_PROGRESS', 'PENDING_APPROVAL', 'PENDING_EMPLOYEE', 'PENDING_MANAGER', 'PREP', 'PROCESSING', 'SUBMITTED', 'UNDER_INVESTIGATION', 'GENERATED', 'PENDING_ACTION'].includes(normalized)) return colors.warning;
    if (['REJECTED', 'DENIED', 'TERMINATED', 'CANCELLED', 'FAILED', 'CRITICAL', 'BLOCKER', 'HIGH'].includes(normalized)) return colors.error;
    if (['OPEN', 'APPLIED', 'AI_SCREENING', 'RECRUITER_SCREEN', 'WAIVED', 'REVIEWED', 'SUBMITTED_REPORT'].includes(normalized)) return colors.info;
    return colors.inkSubtle;
  };

  const MetricCard = ({ label, value, icon: Icon, accent }: { label: string; value: string | number; icon: React.ElementType; accent?: string }) => (
    <div className="rounded-xl p-4 transition-all hover:translate-y-[-1px]"
      style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
      <div className="flex items-start justify-between">
        <div>
          <span className="text-[24px] font-bold tracking-tight" style={{ color: colors.ink, letterSpacing: '-0.6px' }}>{value}</span>
          <p className="text-[11px] mt-1 font-medium" style={{ color: colors.inkSubtle }}>{label}</p>
        </div>
        <div className="w-9 h-9 rounded-lg flex items-center justify-center" style={{ background: (accent || colors.primary) + '15' }}>
          <Icon className="w-4.5 h-4.5" style={{ color: accent || colors.primary }} />
        </div>
      </div>
    </div>
  );

  const Badge = ({ status }: { status: string }) => (
    <span className="text-[11px] font-medium px-2 py-0.5 rounded-full uppercase tracking-wide"
      style={{ background: statusColor(status) + '18', color: statusColor(status) }}>
      {humanize(status) || 'Unknown'}
    </span>
  );

  const EmptyState = ({ icon: Icon, title, sub }: { icon: React.ElementType; title: string; sub: string }) => (
    <div className="rounded-xl p-16 text-center" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
      <Icon className="w-12 h-12 mx-auto mb-4" style={{ color: colors.inkTertiary }} />
      <p className="text-[15px] font-medium" style={{ color: colors.inkSubtle }}>{title}</p>
      <p className="text-[12px] mt-1" style={{ color: colors.inkTertiary }}>{sub}</p>
    </div>
  );

  // Generic column-table used by every new sub-tab below (with EmptyState).
  interface Col<T> { key: string; label: string; render: (row: T) => React.ReactNode; }
  function DataTable<T extends { id: string }>({ rows, columns, minWidth, emptyIcon, emptyTitle, emptySub }: {
    rows: T[]; columns: Col<T>[]; minWidth?: number; emptyIcon: React.ElementType; emptyTitle: string; emptySub: string;
  }) {
    if (rows.length === 0) return <EmptyState icon={emptyIcon} title={emptyTitle} sub={emptySub} />;
    return (
      <TableCard minWidth={minWidth || 640}>
        <table className="w-full">
          <thead>
            <tr style={{ background: colors.surface2 }}>
              {columns.map(c => (
                <th key={c.key} className="text-left text-[11px] font-semibold uppercase tracking-wider px-5 py-2.5" style={{ color: colors.inkSubtle }}>{c.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={r.id} style={{ borderTop: i > 0 ? `1px solid ${colors.hairline}` : undefined }}>
                {columns.map(c => (
                  <td key={c.key} className="px-5 py-3 text-[12px] align-middle" style={{ color: colors.inkMuted }}>{c.render(r)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </TableCard>
    );
  }

  const ActionButton = ({ onClick, busy, icon: Icon, label, accent, disabled }: {
    onClick: () => void; busy: boolean; icon: React.ElementType; label: string; accent?: string; disabled?: boolean;
  }) => (
    <button onClick={onClick} disabled={busy || disabled}
      className="flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-semibold disabled:opacity-50 whitespace-nowrap"
      style={{ background: (accent || colors.primary) + '15', color: accent || colors.primary }}>
      {busy ? <Loader2 className="w-3 h-3 animate-spin" /> : <Icon className="w-3 h-3" />}
      {label}
    </button>
  );

  const HeaderAction = ({ onClick, icon: Icon, label }: { onClick: () => void; icon: React.ElementType; label: string }) => (
    <button onClick={onClick}
      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-semibold text-white"
      style={{ background: colors.primary }}>
      <Icon className="w-3.5 h-3.5" /> {label}
    </button>
  );

  const employeeOptions = employees.map(e => ({ value: e.id, label: `${e.first_name} ${e.last_name}` }));

  // ── DIRECTORY TAB ──
  const renderDirectoryTab = () => {
    const filtered = employees.filter(e => {
      const q = searchQ.toLowerCase();
      const matchName = `${e.first_name} ${e.last_name}`.toLowerCase().includes(q);
      const matchEmail = (e.email || '').toLowerCase().includes(q);
      const matchStatus = statusFilter === 'all' || (e.status || '').toUpperCase() === statusFilter.toUpperCase();
      return (matchName || matchEmail) && matchStatus;
    });

    const statuses = [...new Set(employees.map(e => (e.status || 'ACTIVE').toUpperCase()))];

    return (
      <div className="space-y-4">
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <MetricCard label="Total Headcount" value={employees.length} icon={Users} />
          <MetricCard label="Active" value={employees.filter(e => (e.status || '').toUpperCase() === 'ACTIVE').length} icon={CheckCircle2} accent={colors.success} />
          <MetricCard label="Onboarding" value={employees.filter(e => (e.status || '').toUpperCase() === 'ONBOARDING').length} icon={UserPlus} accent={colors.info} />
          <MetricCard label="On Leave" value={employees.filter(e => (e.status || '').toUpperCase() === 'LEAVE').length} icon={Calendar} accent={colors.warning} />
        </div>

        <div className="flex gap-3 items-center flex-wrap">
          <div className="relative flex-1 min-w-[220px]">
            <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4" style={{ color: colors.inkTertiary }} />
            <input value={searchQ} onChange={e => setSearchQ(e.target.value)}
              placeholder="Search employees by name or email…"
              className="w-full pl-10 pr-4 py-2.5 rounded-lg text-[13px] outline-none transition-all"
              style={{ background: colors.surface1, border: `1px solid ${colors.hairline}`, color: colors.ink }}
              onFocus={e => (e.target.style.borderColor = colors.primary)}
              onBlur={e => (e.target.style.borderColor = colors.hairline)} />
          </div>
          <div className="flex gap-1.5 flex-wrap">
            <button onClick={() => setStatusFilter('all')}
              className="px-3 py-1.5 rounded-full text-[11px] font-medium transition-all"
              style={{
                background: statusFilter === 'all' ? colors.primary : colors.surface1,
                color: statusFilter === 'all' ? '#fff' : colors.inkSubtle,
                border: `1px solid ${statusFilter === 'all' ? colors.primary : colors.hairline}`
              }}>All</button>
            {statuses.map(s => (
              <button key={s} onClick={() => setStatusFilter(s)}
                className="px-3 py-1.5 rounded-full text-[11px] font-medium transition-all"
                style={{
                  background: statusFilter === s ? colors.primary : colors.surface1,
                  color: statusFilter === s ? '#fff' : colors.inkSubtle,
                  border: `1px solid ${statusFilter === s ? colors.primary : colors.hairline}`
                }}>{humanize(s)}</button>
            ))}
          </div>
          <HeaderAction onClick={() => openModal('bamboohr-connect')} icon={Link2} label="Connect BambooHR" />
        </div>

        {filtered.length === 0 ? (
          <EmptyState icon={Users} title="No employees found" sub={employees.length === 0 ? "Connect an HRIS (e.g., BambooHR) with the button above, or try a different search" : "Try adjusting your search or filters"} />
        ) : (
          <TableCard minWidth={560}>
            <table className="w-full">
              <thead>
                <tr style={{ background: colors.surface2 }}>
                  {['Employee', 'Title', 'Location', 'Status', 'Hired'].map(h => (
                    <th key={h} className="text-left text-[11px] font-semibold uppercase tracking-wider px-5 py-3" style={{ color: colors.inkSubtle }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.map((emp, i) => (
                  <tr key={emp.id} className="transition-colors hover:cursor-pointer"
                    style={{ borderTop: i > 0 ? `1px solid ${colors.hairline}` : undefined }}
                    onMouseEnter={e => (e.currentTarget.style.background = colors.surface2)}
                    onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}>
                    <td className="px-5 py-3">
                      <div className="flex items-center gap-3">
                        <div className="w-8 h-8 rounded-full flex items-center justify-center text-[12px] font-bold"
                          style={{ background: colors.primary + '20', color: colors.primary }}>
                          {(emp.first_name || '?')[0]}{(emp.last_name || '?')[0]}
                        </div>
                        <div>
                          <span className="text-[13px] font-medium" style={{ color: colors.ink }}>{emp.first_name} {emp.last_name}</span>
                          {emp.email && <p className="text-[11px]" style={{ color: colors.inkTertiary }}>{emp.email}</p>}
                        </div>
                      </div>
                    </td>
                    <td className="px-5 py-3 text-[12px]" style={{ color: colors.inkMuted }}>{emp.job_title || '-'}</td>
                    <td className="px-5 py-3">
                      <div className="flex items-center gap-1.5">
                        <MapPin className="w-3 h-3" style={{ color: colors.inkTertiary }} />
                        <span className="text-[12px]" style={{ color: colors.inkMuted }}>{emp.location || '-'}</span>
                      </div>
                    </td>
                    <td className="px-5 py-3"><Badge status={emp.status} /></td>
                    <td className="px-5 py-3 text-[12px]" style={{ color: colors.inkTertiary }}>{emp.hire_date || '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableCard>
        )}

        {/* Employee Documents - visible surface for EmployeeDocument (I-9, W-4, offer letters, etc.) */}
        <div className="rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
          <div className="px-5 py-3 flex items-center justify-between" style={{ borderBottom: `1px solid ${colors.hairline}` }}>
            <div className="flex items-center gap-2">
              <FileText className="w-4 h-4" style={{ color: colors.primary }} />
              <span className="text-[14px] font-medium" style={{ color: colors.ink }}>Employee Documents</span>
              <span className="text-[11px] font-mono px-2 py-0.5 rounded-full" style={{ background: colors.primary + '15', color: colors.primary }}>{employeeDocuments.length} total</span>
            </div>
            <HeaderAction onClick={() => openModal('employee-document')} icon={Plus} label="Log Document" />
          </div>
          <div className="p-2">
            <DataTable rows={employeeDocuments} minWidth={640}
              emptyIcon={FileText} emptyTitle="No documents on file" emptySub="I-9s, W-4s, offer letters and handbook acknowledgments appear here."
              columns={[
                { key: 'emp', label: 'Employee', render: d => employeeName(d.employee_id) },
                { key: 'type', label: 'Document', render: d => `${humanize(d.doc_type)}: ${d.title}` },
                { key: 'signed', label: 'Signed', render: d => d.is_signed
                  ? <span className="flex items-center gap-1" style={{ color: colors.success }}><CheckCircle2 className="w-3.5 h-3.5" /> {formatDate(d.signature_date) || 'Yes'}</span>
                  : <ActionButton onClick={() => runAction(`sign-${d.id}`, () => hrApi.signEmployeeDocument(d.id), () => 'Document signed.')} busy={busyId === `sign-${d.id}`} icon={PenLine} label="Mark Signed" /> },
                { key: 'uploaded', label: 'Uploaded', render: d => formatDate(d.uploaded_at) || '-' },
              ]} />
          </div>
        </div>
      </div>
    );
  };

  // ── RECRUITING TAB ──
  const renderRecruitingTab = () => {
    const stageOrder = ['APPLIED', 'AI_SCREENING', 'RECRUITER_SCREEN', 'HM_INTERVIEW', 'PANEL_INTERVIEW', 'OFFER_PREP', 'OFFER_EXTENDED', 'HIRED', 'REJECTED'];
    const stageLabels: Record<string, string> = {
      APPLIED: 'Applied', AI_SCREENING: 'AI Screen', RECRUITER_SCREEN: 'Recruiter',
      HM_INTERVIEW: 'HM Interview', PANEL_INTERVIEW: 'Panel', OFFER_PREP: 'Offer Prep',
      OFFER_EXTENDED: 'Offered', HIRED: 'Hired', REJECTED: 'Rejected'
    };

    return (
      <div className="space-y-4">
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <MetricCard label="Open Requisitions" value={requisitions.filter(r => r.status === 'OPEN').length} icon={Briefcase} />
          <MetricCard label="Active Candidates" value={candidates.filter(c => !['HIRED', 'REJECTED', 'WITHDRAWN'].includes(c.stage)).length} icon={UserPlus} accent={colors.info} />
          <MetricCard label="Avg AI Score" value={candidates.length > 0 ? Math.round(candidates.reduce((a, c) => a + (c.ai_score || 0), 0) / Math.max(candidates.length, 1)) : '-'} icon={Star} accent={colors.warning} />
          <MetricCard label="Hired This Period" value={candidates.filter(c => c.stage === 'HIRED').length} icon={CheckCircle2} accent={colors.success} />
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <HeaderAction onClick={() => setCreateKind('requisition')} icon={Plus} label="New Requisition" />
          <HeaderAction onClick={() => setCreateKind('candidate')} icon={UserPlus} label="Add Candidate" />
        </div>

        {/* Requisitions */}
        <div className="rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
          <div className="px-5 py-3 flex items-center justify-between" style={{ borderBottom: `1px solid ${colors.hairline}` }}>
            <div className="flex items-center gap-2">
              <Briefcase className="w-4 h-4" style={{ color: colors.primary }} />
              <span className="text-[14px] font-medium" style={{ color: colors.ink }}>Job Requisitions</span>
            </div>
            <span className="text-[11px] font-mono px-2 py-0.5 rounded-full" style={{ background: colors.primary + '15', color: colors.primary }}>{requisitions.length} total</span>
          </div>
          {requisitions.length === 0 ? (
            <div className="p-10 text-center text-[13px]" style={{ color: colors.inkTertiary }}>No requisitions yet. Create one above.</div>
          ) : (
            requisitions.map((req, i) => (
              <div key={req.id} className="px-5 py-3 flex items-center justify-between gap-3 flex-wrap transition-colors"
                style={{ borderTop: i > 0 ? `1px solid ${colors.hairline}` : undefined }}
                onMouseEnter={e => (e.currentTarget.style.background = colors.surface2)}
                onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}>
                <div className="flex-1 min-w-[180px]">
                  <span className="text-[13px] font-medium" style={{ color: colors.ink }}>{req.title}</span>
                  <div className="flex items-center gap-3 mt-1">
                    <span className="text-[11px]" style={{ color: colors.inkSubtle }}>{req.department || '-'}</span>
                    {req.headcount && <span className="text-[11px]" style={{ color: colors.inkTertiary }}>{req.headcount} headcount</span>}
                    {req.target_salary_min && req.target_salary_max && (
                      <span className="text-[11px]" style={{ color: colors.inkTertiary }}>${(req.target_salary_min / 1000).toFixed(0)}k - ${(req.target_salary_max / 1000).toFixed(0)}k</span>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-2 flex-wrap">
                  <Badge status={req.status} />
                  <ActionButton onClick={() => handleFairnessSweep(req.id)} busy={busyId === `sweep-${req.id}`}
                    icon={Scale} label="Fairness Sweep" accent="#8b5cf6" />
                  <WorkflowActions domain="hr" entityPath="requisitions" entityId={req.id}
                    currentState={req.status} transitions={workflows['job_requisition']?.transitions}
                    onDone={async (m) => { setActionMsg(m); await loadData(); }} />
                </div>
              </div>
            ))
          )}
        </div>

        {trace && (
          <GateTrace running={screeningId === trace.id} result={trace.result} skillLabel={trace.label} />
        )}

        {/* Interviews */}
        <div className="rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
          <div className="px-5 py-3 flex items-center justify-between" style={{ borderBottom: `1px solid ${colors.hairline}` }}>
            <div className="flex items-center gap-2">
              <Calendar className="w-4 h-4" style={{ color: colors.primary }} />
              <span className="text-[14px] font-medium" style={{ color: colors.ink }}>Interviews</span>
              <span className="text-[11px] font-mono px-2 py-0.5 rounded-full" style={{ background: colors.primary + '15', color: colors.primary }}>{interviews.length} total</span>
            </div>
            <HeaderAction onClick={() => openModal('interview')} icon={Plus} label="Schedule Interview" />
          </div>
          <div className="p-2">
            <DataTable rows={interviews} minWidth={760}
              emptyIcon={Calendar} emptyTitle="No interviews scheduled" emptySub="Schedule one above to start tracking interviewer feedback."
              columns={[
                { key: 'cand', label: 'Candidate', render: iv => candidateName(iv.candidate_id) },
                { key: 'interviewer', label: 'Interviewer', render: iv => employeeName(iv.interviewer_id) },
                { key: 'type', label: 'Type', render: iv => iv.interview_type },
                { key: 'when', label: 'Scheduled', render: iv => formatDate(iv.scheduled_at) || '-' },
                { key: 'outcome', label: 'Outcome', render: iv => iv.feedback_submitted
                  ? <span className="flex items-center gap-1.5"><span className="font-bold" style={{ color: (iv.score || 0) >= 4 ? colors.success : (iv.score || 0) >= 3 ? colors.warning : colors.error }}>{iv.score}/5</span><Badge status={iv.recommendation || ''} /></span>
                  : <ActionButton onClick={() => openModal('interview-feedback', iv.id)} busy={false} icon={PenLine} label="Add Feedback" /> },
              ]} />
          </div>
        </div>

        {/* Candidates Pipeline - Kanban board (columns per backend CandidateStage) */}
        <div className="rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
          <div className="px-5 py-3 flex items-center justify-between" style={{ borderBottom: `1px solid ${colors.hairline}` }}>
            <div className="flex items-center gap-2">
              <Users className="w-4 h-4" style={{ color: colors.primary }} />
              <span className="text-[14px] font-medium" style={{ color: colors.ink }}>Candidate Pipeline</span>
            </div>
            {actionMsg && <span className="text-[11px]" style={{ color: colors.inkSubtle }}>{actionMsg}</span>}
          </div>
          {candidates.length === 0 ? (
            <div className="p-10 text-center text-[13px]" style={{ color: colors.inkTertiary }}>No candidates in the pipeline.</div>
          ) : (
            <div className="p-4 flex gap-3 overflow-x-auto">
              {stageOrder.map(stage => {
                const inStage = candidates.filter(c => c.stage === stage);
                return (
                  <div key={stage} className="flex-shrink-0 w-[240px]">
                    <div className="flex items-center justify-between px-2 py-1.5 mb-2 rounded-md"
                      style={{ background: colors.surface2 }}>
                      <span className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: statusColor(stage) }}>
                        {stageLabels[stage] || humanize(stage)}
                      </span>
                      <span className="text-[11px] font-mono" style={{ color: colors.inkSubtle }}>{inStage.length}</span>
                    </div>
                    <div className="space-y-2">
                      {inStage.map(c => {
                        const execId = provenance[c.id];
                        const next = nextStage(c.stage);
                        return (
                          <div key={c.id} className="rounded-lg p-3"
                            style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                            <div className="flex items-center justify-between">
                              <span className="text-[12px] font-medium truncate" style={{ color: colors.ink }}>{c.name}</span>
                              {c.ai_score != null && (
                                <span className="text-[11px] font-mono font-bold ml-2 flex-shrink-0"
                                  style={{ color: c.ai_score >= 70 ? colors.success : c.ai_score >= 40 ? colors.warning : colors.error }}>
                                  {c.ai_score}
                                </span>
                              )}
                            </div>
                            {c.ai_summary && (
                              <p className="text-[11px] mt-1 line-clamp-2" style={{ color: colors.inkSubtle }}>{c.ai_summary}</p>
                            )}
                            {(c.ai_red_flags || []).length > 0 && (
                              <div className="mt-1.5 space-y-0.5">
                                {(c.ai_red_flags || []).slice(0, 3).map((f, idx) => (
                                  <div key={idx} className="flex items-start gap-1 text-[11px]" style={{ color: colors.error }}>
                                    <ShieldAlert className="w-3 h-3 flex-shrink-0 mt-0.5" />
                                    <span className="line-clamp-1">{f}</span>
                                  </div>
                                ))}
                              </div>
                            )}
                            {execId && (
                              <a href={`/platform/decisions?execution_id=${execId}`}
                                className="mt-1.5 flex items-center gap-1 text-[11px]" style={{ color: colors.primary }}>
                                <ExternalLink className="w-3 h-3" /> Provenance {execId.slice(0, 8)}…
                              </a>
                            )}
                            <div className="mt-2 flex items-center gap-1.5">
                              <ActionButton onClick={() => handleScreen(c.id)} busy={screeningId === c.id} icon={Zap} label="Screen" />
                              {next && (
                                <ActionButton onClick={() => handleAdvance(c.id, next)} busy={advancingId === c.id}
                                  icon={ArrowUpRight} label="Advance" accent={colors.inkSubtle} />
                              )}
                            </div>
                          </div>
                        );
                      })}
                      {inStage.length === 0 && (
                        <div className="text-[11px] text-center py-3 rounded-lg border border-dashed"
                          style={{ color: colors.inkTertiary, borderColor: colors.hairline }}>-</div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    );
  };

  // ── TIME & ATTENDANCE TAB ──
  const renderTimeTab = () => (
    <div className="space-y-4">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard label="Total Requests" value={timeOff.length} icon={Calendar} />
        <MetricCard label="Pending" value={timeOff.filter(t => t.status === 'REQUESTED').length} icon={Clock} accent={colors.warning} />
        <MetricCard label="Approved" value={timeOff.filter(t => t.status === 'APPROVED').length} icon={CheckCircle2} accent={colors.success} />
        <MetricCard label="Denied" value={timeOff.filter(t => t.status === 'DENIED').length} icon={XCircle} accent={colors.error} />
      </div>

      <BulkActionBar domain="hr" entityType="time_off_request" noun="request"
        ids={bulk.ids} count={bulk.size} bulkAllowed={bulk.bulkAllowed}
        onDone={async (m) => { setActionMsg(m); await loadData(); }} onClear={bulk.clear} />
      <TableCard minWidth={680}>
        <div className="px-5 py-3 flex items-center gap-2" style={{ borderBottom: `1px solid ${colors.hairline}` }}>
          <Calendar className="w-4 h-4" style={{ color: colors.primary }} />
          <span className="text-[14px] font-medium" style={{ color: colors.ink }}>Time-Off Requests</span>
        </div>
        {timeOff.length === 0 ? (
          <div className="p-10 text-center text-[13px]" style={{ color: colors.inkTertiary }}>No time-off requests.</div>
        ) : (
          <table className="w-full">
            <thead>
              <tr style={{ background: colors.surface2 }}>
                <th className="px-4 py-2.5 w-8">
                  <input type="checkbox" aria-label="Select all requests"
                    checked={bulk.allSelected} onChange={e => bulk.setAll(e.target.checked)} />
                </th>
                {['Employee', 'Type', 'Start', 'End', 'Hours', 'Status', 'Actions'].map(h => (
                  <th key={h} className="text-left text-[11px] font-semibold uppercase tracking-wider px-5 py-2.5" style={{ color: colors.inkSubtle }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {timeOff.map((t, i) => (
                <tr key={t.id} style={{ borderTop: i > 0 ? `1px solid ${colors.hairline}` : undefined }}>
                  <td className="px-4 py-3">
                    <input type="checkbox" aria-label={`Select request for ${employeeName(t.employee_id)}`}
                      checked={bulk.isSelected(t.id)} onChange={() => bulk.toggle(t.id)} />
                  </td>
                  <td className="px-5 py-3 text-[12px] font-medium" style={{ color: colors.ink }}>{employeeName(t.employee_id)}</td>
                  <td className="px-5 py-3">
                    <span className="text-[11px] font-medium px-2 py-0.5 rounded-full" style={{ background: colors.surface2, color: colors.inkSubtle }}>{humanize(t.leave_type) || '-'}</span>
                  </td>
                  <td className="px-5 py-3 text-[12px]" style={{ color: colors.inkMuted }}>{t.start_date || '-'}</td>
                  <td className="px-5 py-3 text-[12px]" style={{ color: colors.inkMuted }}>{t.end_date || '-'}</td>
                  <td className="px-5 py-3 text-[12px]" style={{ color: colors.inkMuted }}>{t.hours_requested || '-'}</td>
                  <td className="px-5 py-3"><Badge status={t.status} /></td>
                  <td className="px-5 py-3">
                    <WorkflowActions domain="hr" entityPath="time-off-requests" entityId={t.id}
                      currentState={t.status} transitions={workflows['time_off_request']?.transitions}
                      onDone={async (m) => { setActionMsg(m); await loadData(); }} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </TableCard>

      {/* Timesheets */}
      <div className="rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
        <div className="px-5 py-3 flex items-center justify-between" style={{ borderBottom: `1px solid ${colors.hairline}` }}>
          <div className="flex items-center gap-2">
            <Clock className="w-4 h-4" style={{ color: colors.primary }} />
            <span className="text-[14px] font-medium" style={{ color: colors.ink }}>Timesheets</span>
            <span className="text-[11px] font-mono px-2 py-0.5 rounded-full" style={{ background: colors.primary + '15', color: colors.primary }}>{timesheets.length} total</span>
          </div>
          <HeaderAction onClick={() => openModal('timesheet')} icon={Plus} label="File Timesheet" />
        </div>
        <div className="p-2">
          <DataTable rows={timesheets} minWidth={720}
            emptyIcon={Clock} emptyTitle="No timesheets filed" emptySub="Weekly regular/overtime hours per employee appear here."
            columns={[
              { key: 'emp', label: 'Employee', render: t => employeeName(t.employee_id) },
              { key: 'period', label: 'Period', render: t => `${formatDate(t.period_start)} - ${formatDate(t.period_end)}` },
              { key: 'reg', label: 'Regular Hrs', render: t => t.total_regular_hours.toFixed(1) },
              { key: 'ot', label: 'Overtime Hrs', render: t => t.total_overtime_hours.toFixed(1) },
              { key: 'status', label: 'Status', render: t => <Badge status={t.status} /> },
              { key: 'actions', label: 'Actions', render: t => (
                <WorkflowActions domain="hr" entityPath="timesheets" entityId={t.id}
                  currentState={t.status} transitions={workflows['timesheet']?.transitions}
                  onDone={async (m) => { setActionMsg(m); await loadData(); }} />
              ) },
            ]} />
        </div>
      </div>
    </div>
  );

  // ── PERFORMANCE TAB ──
  const renderPerformanceTab = () => {
    const ratingColor = (r: number | null) => {
      if (r == null) return colors.inkTertiary;
      if (r >= 4) return colors.success;
      if (r >= 3) return colors.info;
      if (r >= 2) return colors.warning;
      return colors.error;
    };

    return (
      <div className="space-y-4">
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <MetricCard label="Total Reviews" value={reviews.length} icon={Star} />
          <MetricCard label="Completed" value={reviews.filter(r => r.status === 'COMPLETED').length} icon={CheckCircle2} accent={colors.success} />
          <MetricCard label="In Progress" value={reviews.filter(r => ['DRAFT', 'PENDING_EMPLOYEE', 'PENDING_MANAGER'].includes(r.status)).length} icon={Clock} accent={colors.warning} />
          <MetricCard label="Avg Rating" value={reviews.length > 0 ? (reviews.reduce((a, r) => a + (r.manager_rating || 0), 0) / Math.max(reviews.filter(r => r.manager_rating != null).length, 1)).toFixed(1) : '-'} icon={TrendingUp} accent={colors.info} />
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <HeaderAction onClick={() => openModal('review-cycle')} icon={Plus} label="New Review Cycle" />
          <HeaderAction onClick={() => openModal('performance-review')} icon={Plus} label="Open Review" />
        </div>

        <TableCard minWidth={780}>
          <div className="px-5 py-3 flex items-center gap-2" style={{ borderBottom: `1px solid ${colors.hairline}` }}>
            <Star className="w-4 h-4" style={{ color: colors.primary }} />
            <span className="text-[14px] font-medium" style={{ color: colors.ink }}>Performance Reviews</span>
          </div>
          {reviews.length === 0 ? (
            <div className="p-10 text-center text-[13px]" style={{ color: colors.inkTertiary }}>No performance reviews yet. Open one above.</div>
          ) : (
            <table className="w-full">
              <thead>
                <tr style={{ background: colors.surface2 }}>
                  {['Employee', 'Self Rating', 'Manager Rating', 'Status', 'Actions'].map(h => (
                    <th key={h} className="text-left text-[11px] font-semibold uppercase tracking-wider px-5 py-2.5" style={{ color: colors.inkSubtle }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {reviews.map((rev, i) => (
                  <tr key={rev.id} style={{ borderTop: i > 0 ? `1px solid ${colors.hairline}` : undefined }}>
                    <td className="px-5 py-3 text-[12px] font-medium" style={{ color: colors.ink }}>{employeeName(rev.employee_id)}</td>
                    <td className="px-5 py-3">
                      {rev.self_rating != null ? (
                        <div className="flex items-center gap-1.5">
                          <span className="text-[14px] font-bold" style={{ color: ratingColor(rev.self_rating) }}>{rev.self_rating}</span>
                          <span className="text-[11px]" style={{ color: colors.inkTertiary }}>/ 5</span>
                        </div>
                      ) : <span className="text-[11px]" style={{ color: colors.inkTertiary }}>Pending</span>}
                    </td>
                    <td className="px-5 py-3">
                      {rev.manager_rating != null ? (
                        <div className="flex items-center gap-1.5">
                          <span className="text-[14px] font-bold" style={{ color: ratingColor(rev.manager_rating) }}>{rev.manager_rating}</span>
                          <span className="text-[11px]" style={{ color: colors.inkTertiary }}>/ 5</span>
                        </div>
                      ) : <span className="text-[11px]" style={{ color: colors.inkTertiary }}>Pending</span>}
                    </td>
                    <td className="px-5 py-3"><Badge status={rev.status} /></td>
                    <td className="px-5 py-3">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        {rev.status === 'DRAFT' && (
                          <WorkflowActions domain="hr" entityPath="performance-reviews" entityId={rev.id}
                            currentState={rev.status} transitions={workflows['performance_review']?.transitions}
                            onDone={async (m) => { setActionMsg(m); await loadData(); }} />
                        )}
                        {['DRAFT', 'PENDING_EMPLOYEE'].includes(rev.status) && (
                          <ActionButton onClick={() => openModal('self-rating', rev.id)} busy={false} icon={PenLine} label="Self-Rate" />
                        )}
                        {rev.status === 'PENDING_MANAGER' && (
                          <ActionButton onClick={() => openModal('manager-rating', rev.id)} busy={false} icon={PenLine} label="Manager Rate" accent="#8b5cf6" />
                        )}
                        <ActionButton onClick={() => openModal('synthesize-feedback', rev.id)} busy={false} icon={Sparkles} label="Synthesize 360" accent={colors.info} />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </TableCard>
      </div>
    );
  };

  // ── BENEFITS TAB ──
  const renderBenefitsTab = () => {
    const activeCount = benefitEnrollments.filter(e => e.status === 'ACTIVE').length;
    const verifiedCount = benefitEnrollments.filter(e => e.agent_verified).length;
    return (
      <div className="space-y-4">
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <StatCard label="Benefit Plans" value={benefitPlans.length} icon={<Heart className="w-4 h-4" />} />
          <StatCard label="Total Enrollments" value={benefitEnrollments.length} icon={<Users className="w-4 h-4" />} accent={colors.info} />
          <StatCard label="Active Coverage" value={activeCount} icon={<CheckCircle2 className="w-4 h-4" />} accent={colors.success} />
          <StatCard label="Agent-Verified" value={verifiedCount} icon={<ShieldCheck className="w-4 h-4" />} accent="#8b5cf6" />
        </div>

        <div className="rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
          <div className="px-5 py-3 flex items-center justify-between" style={{ borderBottom: `1px solid ${colors.hairline}` }}>
            <span className="text-[14px] font-medium" style={{ color: colors.ink }}>Benefit Plans</span>
            <HeaderAction onClick={() => openModal('benefit-plan')} icon={Plus} label="New Plan" />
          </div>
          <div className="p-2">
            <DataTable rows={benefitPlans} minWidth={720}
              emptyIcon={Heart} emptyTitle="No benefit plans configured" emptySub="Health, dental, vision, retirement and other plans appear here."
              columns={[
                { key: 'name', label: 'Plan', render: p => p.name },
                { key: 'provider', label: 'Provider', render: p => p.provider },
                { key: 'type', label: 'Type', render: p => <Badge status={p.benefit_type} /> },
                { key: 'cost', label: 'Employee Cost / mo', render: p => `$${p.employee_cost_individual.toFixed(0)}` },
                { key: 'employer', label: 'Employer Contribution', render: p => `$${p.employer_contribution.toFixed(0)}` },
              ]} />
          </div>
        </div>

        <div className="rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
          <div className="px-5 py-3 flex items-center justify-between" style={{ borderBottom: `1px solid ${colors.hairline}` }}>
            <span className="text-[14px] font-medium" style={{ color: colors.ink }}>Enrollments</span>
            <HeaderAction onClick={() => openModal('benefit-enrollment')} icon={Plus} label="Enroll Employee" />
          </div>
          <div className="p-2">
            <DataTable rows={benefitEnrollments} minWidth={860}
              emptyIcon={Users} emptyTitle="No enrollments yet" emptySub="Enroll an employee in a plan above."
              columns={[
                { key: 'emp', label: 'Employee', render: e => employeeName(e.employee_id) },
                { key: 'plan', label: 'Plan', render: e => planName(e.plan_id) },
                { key: 'coverage', label: 'Coverage', render: e => humanize(e.coverage_level) },
                { key: 'status', label: 'Status', render: e => <Badge status={e.status} /> },
                { key: 'verified', label: 'Agent Verified', render: e => e.agent_verified
                  ? <span className="flex items-center gap-1" style={{ color: colors.success }}><ShieldCheck className="w-3.5 h-3.5" /> Verified</span>
                  : <ActionButton onClick={() => runAction(`verify-${e.id}`, () => hrApi.verifyBenefitEnrollment(e.id), r => r.verified ? 'Eligibility verified.' : `Verification routed for review (${humanize(r.status)}).`)} busy={busyId === `verify-${e.id}`} icon={ShieldCheck} label="Verify" /> },
                { key: 'actions', label: 'Actions', render: e => (
                  <WorkflowActions domain="hr" entityPath="benefit-enrollments" entityId={e.id}
                    currentState={e.status} transitions={workflows['benefit_enrollment']?.transitions}
                    onDone={async (m) => { setActionMsg(m); await loadData(); }} />
                ) },
              ]} />
          </div>
        </div>
      </div>
    );
  };

  // ── COMPENSATION TAB ──
  const renderCompensationTab = () => {
    const current = compensation.filter(c => c.is_current);
    const avgBase = current.length ? Math.round(current.reduce((a, c) => a + c.base_amount, 0) / current.length) : 0;
    return (
      <div className="space-y-4">
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <StatCard label="Current Records" value={current.length} icon={<Wallet className="w-4 h-4" />} />
          <StatCard label="Avg Base Salary" value={avgBase} format="currency" icon={<DollarSign className="w-4 h-4" />} accent={colors.success} />
          <StatCard label="Total Compensation Records" value={compensation.length} icon={<LineChart className="w-4 h-4" />} accent={colors.info} />
          <StatCard label="With Equity Grants" value={current.filter(c => c.equity_grant > 0).length} icon={<TrendingUp className="w-4 h-4" />} accent="#8b5cf6" />
        </div>

        <div className="rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
          <div className="px-5 py-3 flex items-center justify-between" style={{ borderBottom: `1px solid ${colors.hairline}` }}>
            <span className="text-[14px] font-medium" style={{ color: colors.ink }}>Compensation Records</span>
            <HeaderAction onClick={() => openModal('compensation')} icon={Plus} label="New Record" />
          </div>
          <div className="p-2">
            <DataTable rows={compensation} minWidth={980}
              emptyIcon={Wallet} emptyTitle="No compensation records" emptySub="Create one above to track base pay, bonus and equity per employee."
              columns={[
                { key: 'emp', label: 'Employee', render: c => employeeName(c.employee_id) },
                { key: 'type', label: 'Type', render: c => humanize(c.comp_type) },
                { key: 'base', label: 'Base Amount', render: c => `$${c.base_amount.toLocaleString()}` },
                { key: 'bonus', label: 'Target Bonus', render: c => `${c.target_bonus_pct}%` },
                { key: 'equity', label: 'Equity', render: c => c.equity_grant > 0 ? `${c.equity_grant.toLocaleString()} ${c.equity_type || ''}`.trim() : '-' },
                { key: 'effective', label: 'Effective', render: c => formatDate(c.effective_date) || '-' },
                { key: 'current', label: 'Current', render: c => c.is_current ? <Badge status="ACTIVE" /> : <span style={{ color: colors.inkTertiary }}>Superseded</span> },
                { key: 'actions', label: 'Actions', render: c => c.is_current
                  ? <ActionButton onClick={() => runAction(`market-${c.id}`, () => hrApi.compensationMarketAnalysis(c.id), () => 'Market analysis complete.')} busy={busyId === `market-${c.id}`} icon={Gauge} label="Market Analysis" accent="#8b5cf6" />
                  : null },
              ]} />
          </div>
        </div>
      </div>
    );
  };

  // ── ONBOARDING / OFFBOARDING TAB ──
  const renderOnboardingTab = () => {
    const onboarding = boardingPlans.filter(p => p.plan_type === 'ONBOARDING');
    const offboarding = boardingPlans.filter(p => p.plan_type === 'OFFBOARDING');
    return (
      <div className="space-y-4">
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <MetricCard label="Onboarding Plans" value={onboarding.length} icon={LogIn} accent={colors.info} />
          <MetricCard label="Offboarding Plans" value={offboarding.length} icon={LogOut} accent={colors.warning} />
          <MetricCard label="Active Plans" value={boardingPlans.filter(p => p.status === 'ACTIVE').length} icon={Clock} />
          <MetricCard label="Tasks Completed" value={boardingPlans.reduce((a, p) => a + p.completed_tasks, 0)} icon={CheckCircle2} accent={colors.success} />
        </div>

        <HeaderAction onClick={() => openModal('boarding-plan')} icon={Plus} label="New Boarding Plan" />

        <div className="rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
          <div className="px-5 py-3" style={{ borderBottom: `1px solid ${colors.hairline}` }}>
            <span className="text-[14px] font-medium" style={{ color: colors.ink }}>Boarding Plans</span>
          </div>
          <div className="p-2">
            <DataTable rows={boardingPlans} minWidth={820}
              emptyIcon={LogIn} emptyTitle="No onboarding or offboarding plans" emptySub="Create one above, or trigger an exit interview for a terminated employee."
              columns={[
                { key: 'emp', label: 'Employee', render: p => employeeName(p.employee_id) },
                { key: 'type', label: 'Type', render: p => <Badge status={p.plan_type} /> },
                { key: 'progress', label: 'Progress', render: p => (
                  <div className="flex items-center gap-2 min-w-[100px]">
                    <div className="flex-1 h-2 rounded-full" style={{ background: colors.canvas }}>
                      <div className="h-2 rounded-full transition-all duration-500"
                        style={{ width: `${p.total_tasks ? Math.round((p.completed_tasks / p.total_tasks) * 100) : 0}%`, background: colors.success }} />
                    </div>
                    <span className="text-[11px] font-mono" style={{ color: colors.inkSubtle }}>{p.completed_tasks}/{p.total_tasks}</span>
                  </div>
                ) },
                { key: 'status', label: 'Status', render: p => <Badge status={p.status} /> },
                { key: 'start', label: 'Start', render: p => formatDate(p.start_date) || '-' },
                { key: 'actions', label: 'Actions', render: p => p.plan_type === 'ONBOARDING'
                  ? <ActionButton onClick={() => openModal('onboarding-checkin', p.employee_id)} busy={false} icon={LogIn} label="Check In" />
                  : p.plan_type === 'OFFBOARDING'
                    ? <ActionButton onClick={() => openModal('exit-interview', p.employee_id)} busy={false} icon={LogOut} label="Exit Interview" accent={colors.warning} />
                    : null },
              ]} />
          </div>
        </div>

        <div className="rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
          <div className="px-5 py-3" style={{ borderBottom: `1px solid ${colors.hairline}` }}>
            <span className="text-[14px] font-medium" style={{ color: colors.ink }}>Tasks</span>
          </div>
          <div className="p-2">
            <DataTable rows={boardingTasks} minWidth={780}
              emptyIcon={CheckCircle2} emptyTitle="No boarding tasks" emptySub="Tasks for onboarding/offboarding plans appear here."
              columns={[
                { key: 'emp', label: 'Employee', render: t => boardingPlanOwner(t.plan_id) },
                { key: 'title', label: 'Task', render: t => t.title },
                { key: 'due', label: 'Due', render: t => formatDate(t.due_date) || '-' },
                { key: 'status', label: 'Status', render: t => <Badge status={t.status} /> },
                { key: 'actions', label: 'Actions', render: t => (
                  <WorkflowActions domain="hr" entityPath="boarding-tasks" entityId={t.id}
                    currentState={t.status} transitions={workflows['boarding_task']?.transitions}
                    onDone={async (m) => { setActionMsg(m); await loadData(); }} />
                ) },
              ]} />
          </div>
        </div>
      </div>
    );
  };

  // ── LEARNING TAB ──
  const renderLearningTab = () => {
    const completed = courseEnrollments.filter(e => e.status === 'COMPLETED').length;
    const completionRate = courseEnrollments.length ? Math.round((completed / courseEnrollments.length) * 100) : 0;
    return (
      <div className="space-y-4">
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <StatCard label="Courses" value={courses.length} icon={<GraduationCap className="w-4 h-4" />} />
          <StatCard label="Enrollments" value={courseEnrollments.length} icon={<Users className="w-4 h-4" />} accent={colors.info} />
          <StatCard label="Completion Rate" value={completionRate} format="percent" icon={<CheckCircle2 className="w-4 h-4" />} accent={colors.success} />
          <StatCard label="Compliance Courses" value={courses.filter(c => c.is_required_for_compliance).length} icon={<ShieldCheck className="w-4 h-4" />} accent="#8b5cf6" />
        </div>

        <div className="rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
          <div className="px-5 py-3 flex items-center justify-between" style={{ borderBottom: `1px solid ${colors.hairline}` }}>
            <span className="text-[14px] font-medium" style={{ color: colors.ink }}>Courses</span>
            <HeaderAction onClick={() => openModal('course')} icon={Plus} label="New Course" />
          </div>
          <div className="p-2">
            <DataTable rows={courses} minWidth={720}
              emptyIcon={GraduationCap} emptyTitle="No courses in the catalog" emptySub="Add a course above to start assigning training."
              columns={[
                { key: 'title', label: 'Course', render: c => c.title },
                { key: 'provider', label: 'Provider', render: c => c.provider || '-' },
                { key: 'compliance', label: 'Compliance', render: c => c.is_required_for_compliance ? <Badge status="ACTIVE" /> : <span style={{ color: colors.inkTertiary }}>Optional</span> },
                { key: 'minutes', label: 'Duration', render: c => `${c.estimated_minutes} min` },
              ]} />
          </div>
        </div>

        <div className="rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
          <div className="px-5 py-3 flex items-center justify-between" style={{ borderBottom: `1px solid ${colors.hairline}` }}>
            <span className="text-[14px] font-medium" style={{ color: colors.ink }}>Enrollments</span>
            <HeaderAction onClick={() => openModal('course-enrollment')} icon={Plus} label="Enroll Employee" />
          </div>
          <div className="p-2">
            <DataTable rows={courseEnrollments} minWidth={860}
              emptyIcon={Users} emptyTitle="No course enrollments" emptySub="Enroll an employee in a course above."
              columns={[
                { key: 'emp', label: 'Employee', render: e => employeeName(e.employee_id) },
                { key: 'course', label: 'Course', render: e => courseName(e.course_id) },
                { key: 'progress', label: 'Progress', render: e => (
                  <div className="flex items-center gap-2 min-w-[100px]">
                    <div className="flex-1 h-2 rounded-full" style={{ background: colors.canvas }}>
                      <div className="h-2 rounded-full transition-all duration-500" style={{ width: `${e.progress_pct}%`, background: colors.primary }} />
                    </div>
                    <span className="text-[11px] font-mono" style={{ color: colors.inkSubtle }}>{Math.round(e.progress_pct)}%</span>
                  </div>
                ) },
                { key: 'status', label: 'Status', render: e => <Badge status={e.status} /> },
                { key: 'actions', label: 'Actions', render: e => (
                  <WorkflowActions domain="hr" entityPath="course-enrollments" entityId={e.id}
                    currentState={e.status} transitions={workflows['course_enrollment']?.transitions}
                    onDone={async (m) => { setActionMsg(m); await loadData(); }} />
                ) },
              ]} />
          </div>
        </div>
      </div>
    );
  };

  // ── EMPLOYEE RELATIONS TAB ──
  const renderERTab = () => (
    <div className="space-y-4">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard label="Open Cases" value={erCases.filter(c => c.status === 'OPEN').length} icon={ShieldAlert} accent={colors.error} />
        <MetricCard label="Under Investigation" value={erCases.filter(c => c.status === 'UNDER_INVESTIGATION').length} icon={Search} accent={colors.warning} />
        <MetricCard label="Resolved" value={erCases.filter(c => ['RESOLVED', 'CLOSED'].includes(c.status)).length} icon={CheckCircle2} accent={colors.success} />
        <MetricCard label="Total Cases" value={erCases.length} icon={Scale} />
      </div>

      <HeaderAction onClick={() => openModal('er-case')} icon={Plus} label="Open Case" />

      <div className="rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
        <div className="p-2">
          <DataTable rows={erCases} minWidth={980}
            emptyIcon={Scale} emptyTitle="No employee relations cases" emptySub="Open a case above to start tracking a complaint or investigation."
            columns={[
              { key: 'title', label: 'Case', render: c => c.title },
              { key: 'category', label: 'Category', render: c => humanize(c.category) },
              { key: 'severity', label: 'Severity', render: c => <Badge status={c.severity} /> },
              { key: 'status', label: 'Status', render: c => <Badge status={c.status} /> },
              { key: 'reporter', label: 'Reporter', render: c => employeeName(c.reporter_id) },
              { key: 'accused', label: 'Involved', render: c => employeeName(c.accused_id) },
              { key: 'actions', label: 'Actions', render: c => (
                <div className="flex items-center gap-1.5 flex-wrap">
                  {c.status === 'OPEN' && (
                    <ActionButton onClick={() => runAction(`triage-${c.id}`, () => hrApi.triageERCase(c.id), () => 'Triage complete.')} busy={busyId === `triage-${c.id}`} icon={Sparkles} label="Triage" accent="#8b5cf6" />
                  )}
                  <WorkflowActions domain="hr" entityPath="er-cases" entityId={c.id}
                    currentState={c.status} transitions={workflows['er_case']?.transitions}
                    onDone={async (m) => { setActionMsg(m); await loadData(); }} />
                </div>
              ) },
            ]} />
        </div>
      </div>

      {erCases.some(c => c.ai_risk_assessment) && (
        <div className="rounded-xl p-4 space-y-2" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
          <span className="text-[12px] font-semibold uppercase tracking-wide" style={{ color: colors.inkSubtle }}>AI Risk Assessments</span>
          {erCases.filter(c => c.ai_risk_assessment).map(c => (
            <div key={c.id} className="text-[12px]" style={{ color: colors.inkMuted }}>
              <span className="font-medium" style={{ color: colors.ink }}>{c.title}:</span> {c.ai_risk_assessment}
            </div>
          ))}
        </div>
      )}
    </div>
  );

  // ── PAYROLL TAB ──
  const renderPayrollTab = () => {
    const latest = payrollRuns[0];
    return (
      <div className="space-y-4">
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <StatCard label="Payroll Runs" value={payrollRuns.length} icon={<DollarSign className="w-4 h-4" />} />
          <StatCard label="Latest Gross" value={Math.round(latest?.total_gross || 0)} format="currency" icon={<Wallet className="w-4 h-4" />} accent={colors.success} />
          <StatCard label="Pending Approval" value={payrollRuns.filter(r => r.status === 'PENDING_APPROVAL').length} icon={<Clock className="w-4 h-4" />} accent={colors.warning} />
          <StatCard label="Payslips Generated" value={payslips.length} icon={<FileText className="w-4 h-4" />} accent={colors.info} />
        </div>

        <HeaderAction onClick={() => openModal('payroll-run')} icon={Plus} label="New Payroll Run" />

        <div className="rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
          <div className="px-5 py-3" style={{ borderBottom: `1px solid ${colors.hairline}` }}>
            <span className="text-[14px] font-medium" style={{ color: colors.ink }}>Payroll Runs</span>
          </div>
          <div className="p-2">
            <DataTable rows={payrollRuns} minWidth={920}
              emptyIcon={DollarSign} emptyTitle="No payroll runs" emptySub="Create one above, then generate payslips against real current compensation."
              columns={[
                { key: 'period', label: 'Period', render: r => `${formatDate(r.period_start)} - ${formatDate(r.period_end)}` },
                { key: 'pay', label: 'Pay Date', render: r => formatDate(r.pay_date) || '-' },
                { key: 'gross', label: 'Gross', render: r => `$${r.total_gross.toLocaleString()}` },
                { key: 'net', label: 'Net', render: r => `$${r.total_net.toLocaleString()}` },
                { key: 'status', label: 'Status', render: r => <Badge status={r.status} /> },
                { key: 'actions', label: 'Actions', render: r => (
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <ActionButton onClick={() => runAction(`payslips-${r.id}`, () => hrApi.generatePayslips(r.id), res => `${res.created} payslips generated (${res.skipped_existing} already existed).`)} busy={busyId === `payslips-${r.id}`} icon={FileText} label="Generate Payslips" />
                    <WorkflowActions domain="hr" entityPath="payroll-runs" entityId={r.id}
                      currentState={r.status} transitions={workflows['payroll_run']?.transitions}
                      onDone={async (m) => { setActionMsg(m); await loadData(); }} />
                  </div>
                ) },
              ]} />
          </div>
        </div>

        <div className="rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
          <div className="px-5 py-3" style={{ borderBottom: `1px solid ${colors.hairline}` }}>
            <span className="text-[14px] font-medium" style={{ color: colors.ink }}>Payslips</span>
          </div>
          <div className="p-2">
            <DataTable rows={payslips} minWidth={720}
              emptyIcon={FileText} emptyTitle="No payslips generated yet" emptySub="Generate payslips for a run above."
              columns={[
                { key: 'emp', label: 'Employee', render: p => employeeName(p.employee_id) },
                { key: 'period', label: 'Run Period', render: p => runPeriodLabel(p.run_id) },
                { key: 'gross', label: 'Gross Pay', render: p => `$${p.gross_pay.toLocaleString()}` },
                { key: 'net', label: 'Net Pay', render: p => `$${p.net_pay.toLocaleString()}` },
              ]} />
          </div>
        </div>
      </div>
    );
  };

  // ── WORKFORCE PLANNING TAB ──
  const renderPlanningTab = () => (
    <div className="space-y-4">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Headcount Plans" value={headcountPlans.length} icon={<Users className="w-4 h-4" />} />
        <StatCard label="Active Plans" value={headcountPlans.filter(p => p.status === 'ACTIVE').length} icon={<CheckCircle2 className="w-4 h-4" />} accent={colors.success} />
        <StatCard label="Total Budget" value={Math.round(headcountPlans.reduce((a, p) => a + p.budget_allocated, 0))} format="currency" icon={<DollarSign className="w-4 h-4" />} accent={colors.info} />
        <StatCard label="Planned Positions" value={headcountPlans.reduce((a, p) => a + p.planned_positions.reduce((s, pos) => s + pos.count, 0), 0)} icon={<UserPlus className="w-4 h-4" />} accent="#8b5cf6" />
      </div>

      <HeaderAction onClick={() => openModal('headcount-plan')} icon={Plus} label="New Headcount Plan" />

      <div className="rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
        <div className="p-2">
          <DataTable rows={headcountPlans} minWidth={920}
            emptyIcon={Users} emptyTitle="No headcount plans" emptySub="Create a strategic plan above for a department's hiring targets."
            columns={[
              { key: 'name', label: 'Plan', render: p => p.name },
              { key: 'dept', label: 'Department', render: p => p.department_id || '-' },
              { key: 'year', label: 'Year', render: p => p.target_year },
              { key: 'budget', label: 'Budget', render: p => `$${p.budget_allocated.toLocaleString()}` },
              { key: 'positions', label: 'Positions', render: p => p.planned_positions.map(pos => `${pos.count}x ${pos.title}`).join(', ') || '-' },
              { key: 'status', label: 'Status', render: p => <Badge status={p.status} /> },
              { key: 'actions', label: 'Actions', render: p => (
                <WorkflowActions domain="hr" entityPath="headcount-plans" entityId={p.id}
                  currentState={p.status} transitions={workflows['headcount_plan']?.transitions}
                  onDone={async (m) => { setActionMsg(m); await loadData(); }} />
              ) },
            ]} />
        </div>
      </div>
    </div>
  );

  // ── COMPLIANCE TAB ──
  const renderComplianceTab = () => {
    const unresolvedCount = complianceViolations.filter(v => !v.resolved).length;
    return (
      <div className="space-y-4">
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <StatCard label="Compliance Reports" value={complianceReports.length} icon={<ShieldCheck className="w-4 h-4" />} />
          <StatCard label="Unresolved Violations" value={unresolvedCount} icon={<ShieldAlert className="w-4 h-4" />} accent={unresolvedCount ? colors.error : colors.success} />
          <StatCard label="Frameworks Covered" value={new Set(complianceReports.map(r => r.framework)).size} icon={<Scale className="w-4 h-4" />} accent={colors.info} />
          <StatCard label="Metric Snapshots" value={hrMetrics.length} icon={<LineChart className="w-4 h-4" />} accent="#8b5cf6" />
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <HeaderAction onClick={() => openModal('compliance-report')} icon={Plus} label="Log Report" />
          <ActionButton onClick={() => runAction('eeoc-generate', () => hrApi.generateEeocReport(), r => r.passed ? `EEOC audit passed (${r.decided_total} candidates evaluated).` : `EEOC audit flagged adverse impact on ${r.flagged.map(humanize).join(', ')}.`)} busy={busyId === 'eeoc-generate'} icon={Scale} label="Run EEOC Audit" accent="#8b5cf6" />
          <ActionButton onClick={() => runAction('hr-snapshot', () => hrApi.generateHRMetricSnapshot(), () => 'HR metric snapshot generated.')} busy={busyId === 'hr-snapshot'} icon={LineChart} label="Take Metric Snapshot" accent={colors.info} />
        </div>

        <div className="rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
          <div className="px-5 py-3" style={{ borderBottom: `1px solid ${colors.hairline}` }}>
            <span className="text-[14px] font-medium" style={{ color: colors.ink }}>Compliance Reports</span>
          </div>
          <div className="p-2">
            <DataTable rows={complianceReports} minWidth={780}
              emptyIcon={ShieldCheck} emptyTitle="No compliance reports" emptySub="Run the EEOC audit above, or log a manually-compiled report."
              columns={[
                { key: 'framework', label: 'Framework', render: r => <Badge status={r.framework} /> },
                { key: 'name', label: 'Report', render: r => r.report_name },
                { key: 'year', label: 'Year', render: r => r.period_year },
                { key: 'status', label: 'Status', render: r => <Badge status={r.status} /> },
                { key: 'generated', label: 'Generated', render: r => formatDate(r.generated_at) || '-' },
              ]} />
          </div>
        </div>

        <div className="rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
          <div className="px-5 py-3" style={{ borderBottom: `1px solid ${colors.hairline}` }}>
            <span className="text-[14px] font-medium" style={{ color: colors.ink }}>Violations</span>
          </div>
          <div className="p-2">
            <DataTable rows={complianceViolations} minWidth={780}
              emptyIcon={ShieldAlert} emptyTitle="No violations recorded" emptySub="Compliance gate blocks and manually-logged issues appear here."
              columns={[
                { key: 'framework', label: 'Framework', render: v => <Badge status={v.framework} /> },
                { key: 'severity', label: 'Severity', render: v => <Badge status={v.severity} /> },
                { key: 'description', label: 'Description', render: v => <span className="line-clamp-2">{v.description}</span> },
                { key: 'status', label: 'Status', render: v => v.resolved ? <Badge status="RESOLVED" /> : <Badge status="OPEN" /> },
                { key: 'actions', label: 'Actions', render: v => v.resolved
                  ? <span className="text-[11px]" style={{ color: colors.inkTertiary }}>{v.resolution_notes}</span>
                  : <ActionButton onClick={() => openModal('resolve-violation', v.id)} busy={false} icon={CheckCircle2} label="Resolve" /> },
              ]} />
          </div>
        </div>
      </div>
    );
  };

  // ── TABS CONFIG ──
  const TABS: { id: HRTab; label: string; icon: React.ElementType }[] = [
    { id: 'directory', label: 'Directory', icon: Users },
    { id: 'recruiting', label: 'Recruiting', icon: Briefcase },
    { id: 'time', label: 'Time & Attendance', icon: Calendar },
    { id: 'performance', label: 'Performance', icon: Star },
    { id: 'benefits', label: 'Benefits', icon: Heart },
    { id: 'compensation', label: 'Compensation', icon: DollarSign },
    { id: 'onboarding', label: 'Onboarding', icon: LogIn },
    { id: 'learning', label: 'Learning', icon: GraduationCap },
    { id: 'er', label: 'ER Cases', icon: Scale },
    { id: 'payroll', label: 'Payroll', icon: Wallet },
    { id: 'planning', label: 'Workforce Planning', icon: LineChart },
    { id: 'compliance', label: 'Compliance', icon: ShieldCheck },
    { id: 'analytics', label: 'Analytics', icon: BarChart3 },
  ];

  // ── Modal field configs (dispatched via handleModalSubmit above) ──
  const modalConfig: Record<ModalKind, { title: string; submitLabel: string; icon: React.ElementType; fields: QField[] }> = {
    'benefit-plan': {
      title: 'New Benefit Plan', submitLabel: 'Create', icon: Heart,
      fields: [
        { key: 'name', label: 'Plan Name', type: 'text', required: true },
        { key: 'provider', label: 'Provider', type: 'text', required: true },
        { key: 'benefit_type', label: 'Type', type: 'select', required: true, options: ['HEALTH', 'DENTAL', 'VISION', 'LIFE_INSURANCE', 'RETIREMENT', 'FSA_HSA', 'PERKS'].map(v => ({ value: v, label: humanize(v) })) },
        { key: 'employee_cost_individual', label: 'Employee Cost / mo', type: 'number' },
        { key: 'employer_contribution', label: 'Employer Contribution / mo', type: 'number' },
        { key: 'description', label: 'Description', type: 'textarea' },
      ],
    },
    'benefit-enrollment': {
      title: 'Enroll Employee in Benefit', submitLabel: 'Enroll', icon: Heart,
      fields: [
        { key: 'employee_id', label: 'Employee', type: 'select', required: true, options: employeeOptions },
        { key: 'plan_id', label: 'Plan', type: 'select', required: true, options: benefitPlans.map(p => ({ value: p.id, label: p.name })) },
        { key: 'coverage_level', label: 'Coverage Level', type: 'select', defaultValue: 'INDIVIDUAL', options: ['INDIVIDUAL', 'INDIVIDUAL_PLUS_ONE', 'FAMILY'].map(v => ({ value: v, label: humanize(v) })) },
        { key: 'effective_date', label: 'Effective Date', type: 'date', required: true },
      ],
    },
    compensation: {
      title: 'New Compensation Record', submitLabel: 'Create', icon: Wallet,
      fields: [
        { key: 'employee_id', label: 'Employee', type: 'select', required: true, options: employeeOptions },
        { key: 'comp_type', label: 'Type', type: 'select', defaultValue: 'SALARY', options: ['SALARY', 'HOURLY', 'COMMISSION', 'BONUS', 'EQUITY'].map(v => ({ value: v, label: humanize(v) })) },
        { key: 'base_amount', label: 'Base Amount', type: 'number', required: true },
        { key: 'effective_date', label: 'Effective Date', type: 'date', required: true },
        { key: 'change_reason', label: 'Reason', type: 'text', placeholder: 'e.g. New hire, Merit increase' },
      ],
    },
    'boarding-plan': {
      title: 'New Boarding Plan', submitLabel: 'Create', icon: LogIn,
      fields: [
        { key: 'employee_id', label: 'Employee', type: 'select', required: true, options: employeeOptions },
        { key: 'plan_type', label: 'Plan Type', type: 'select', defaultValue: 'ONBOARDING', options: ['ONBOARDING', 'OFFBOARDING', 'CROSSBOARDING'].map(v => ({ value: v, label: humanize(v) })) },
        { key: 'start_date', label: 'Start Date', type: 'date', required: true },
        { key: 'tasks', label: 'Tasks (comma-separated, optional - defaults used if blank)', type: 'textarea' },
      ],
    },
    'onboarding-checkin': {
      title: 'New-Hire Check-In', submitLabel: 'Run Check-In', icon: LogIn,
      fields: [
        { key: 'week_num', label: 'Week Number', type: 'number', required: true, defaultValue: '1' },
        { key: 'response', label: "New Hire's Response", type: 'textarea', placeholder: 'What they said, if anything' },
      ],
    },
    'exit-interview': {
      title: 'Exit Interview', submitLabel: 'Analyze', icon: LogOut,
      fields: [
        { key: 'reason_for_leaving', label: 'Reason for Leaving', type: 'text' },
        { key: 'would_recommend', label: 'Would Recommend the Company', type: 'select', options: [{ value: 'Yes', label: 'Yes' }, { value: 'No', label: 'No' }] },
        { key: 'additional_comments', label: 'Additional Comments', type: 'textarea' },
      ],
    },
    course: {
      title: 'New Course', submitLabel: 'Create', icon: GraduationCap,
      fields: [
        { key: 'title', label: 'Title', type: 'text', required: true },
        { key: 'provider', label: 'Provider', type: 'text', placeholder: 'Internal, Coursera, etc.' },
        { key: 'is_required_for_compliance', label: 'Required for Compliance', type: 'select', options: [{ value: 'no', label: 'No' }, { value: 'yes', label: 'Yes' }] },
        { key: 'estimated_minutes', label: 'Duration (minutes)', type: 'number', defaultValue: '60' },
      ],
    },
    'course-enrollment': {
      title: 'Enroll Employee in Course', submitLabel: 'Enroll', icon: GraduationCap,
      fields: [
        { key: 'employee_id', label: 'Employee', type: 'select', required: true, options: employeeOptions },
        { key: 'course_id', label: 'Course', type: 'select', required: true, options: courses.map(c => ({ value: c.id, label: c.title })) },
      ],
    },
    'er-case': {
      title: 'Open ER Case', submitLabel: 'Open Case', icon: Scale,
      fields: [
        { key: 'title', label: 'Title', type: 'text', required: true },
        { key: 'description', label: 'Description', type: 'textarea', required: true },
        { key: 'category', label: 'Category', type: 'select', required: true, options: ['HARASSMENT', 'POLICY_VIOLATION', 'DISPUTE', 'DISCRIMINATION', 'SAFETY', 'OTHER'].map(v => ({ value: v, label: humanize(v) })) },
        { key: 'severity', label: 'Severity', type: 'select', defaultValue: 'MEDIUM', options: ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'].map(v => ({ value: v, label: humanize(v) })) },
        { key: 'reporter_id', label: 'Reporter (optional)', type: 'select', options: employeeOptions },
        { key: 'accused_id', label: 'Involved Employee (optional)', type: 'select', options: employeeOptions },
      ],
    },
    'headcount-plan': {
      title: 'New Headcount Plan', submitLabel: 'Create', icon: LineChart,
      fields: [
        { key: 'name', label: 'Plan Name', type: 'text', required: true },
        { key: 'department_id', label: 'Department', type: 'text' },
        { key: 'target_year', label: 'Target Year', type: 'number', required: true, defaultValue: String(new Date().getFullYear()) },
        { key: 'budget_allocated', label: 'Budget Allocated', type: 'number' },
        { key: 'position_title', label: 'Position Title', type: 'text', placeholder: 'e.g. Senior Engineer' },
        { key: 'position_count', label: 'Position Count', type: 'number', defaultValue: '1' },
      ],
    },
    'payroll-run': {
      title: 'New Payroll Run', submitLabel: 'Create', icon: Wallet,
      fields: [
        { key: 'period_start', label: 'Period Start', type: 'date', required: true },
        { key: 'period_end', label: 'Period End', type: 'date', required: true },
        { key: 'pay_date', label: 'Pay Date', type: 'date', required: true },
      ],
    },
    'compliance-report': {
      title: 'Log Compliance Report', submitLabel: 'Log Report', icon: ShieldCheck,
      fields: [
        { key: 'framework', label: 'Framework', type: 'select', required: true, options: ['EEOC', 'OSHA', 'HIPAA', 'I9', 'GDPR', 'ACA'].map(v => ({ value: v, label: v })) },
        { key: 'report_name', label: 'Report Name', type: 'text', required: true },
        { key: 'period_year', label: 'Period Year', type: 'number', required: true, defaultValue: String(new Date().getFullYear()) },
      ],
    },
    'resolve-violation': {
      title: 'Resolve Violation', submitLabel: 'Resolve', icon: CheckCircle2,
      fields: [{ key: 'resolution_notes', label: 'Resolution Notes', type: 'textarea', required: true }],
    },
    interview: {
      title: 'Schedule Interview', submitLabel: 'Schedule', icon: Calendar,
      fields: [
        { key: 'candidate_id', label: 'Candidate', type: 'select', required: true, options: candidates.map(c => ({ value: c.id, label: c.name })) },
        { key: 'interviewer_id', label: 'Interviewer', type: 'select', required: true, options: employeeOptions },
        { key: 'scheduled_at', label: 'Scheduled Date', type: 'date', required: true },
        { key: 'interview_type', label: 'Type', type: 'select', required: true, options: ['Technical', 'Behavioral', 'System Design', 'Hiring Manager', 'Panel'].map(v => ({ value: v, label: v })) },
      ],
    },
    'interview-feedback': {
      title: 'Interview Feedback', submitLabel: 'Submit', icon: PenLine,
      fields: [
        { key: 'score', label: 'Score (1-5)', type: 'select', required: true, options: ['1', '2', '3', '4', '5'].map(v => ({ value: v, label: v })) },
        { key: 'recommendation', label: 'Recommendation', type: 'select', required: true, options: ['STRONG_HIRE', 'HIRE', 'NO_HIRE', 'STRONG_NO_HIRE'].map(v => ({ value: v, label: humanize(v) })) },
        { key: 'notes', label: 'Notes', type: 'textarea' },
      ],
    },
    'employee-document': {
      title: 'Log Employee Document', submitLabel: 'Log', icon: FileText,
      fields: [
        { key: 'employee_id', label: 'Employee', type: 'select', required: true, options: employeeOptions },
        { key: 'doc_type', label: 'Document Type', type: 'select', required: true, options: ['I9', 'W4', 'OFFER_LETTER', 'HANDBOOK_ACK', 'PERFORMANCE_REVIEW', 'DISCIPLINARY', 'OTHER'].map(v => ({ value: v, label: humanize(v) })) },
        { key: 'title', label: 'Title', type: 'text', required: true },
      ],
    },
    timesheet: {
      title: 'File Timesheet', submitLabel: 'File', icon: Clock,
      fields: [
        { key: 'employee_id', label: 'Employee', type: 'select', required: true, options: employeeOptions },
        { key: 'period_start', label: 'Period Start', type: 'date', required: true },
        { key: 'period_end', label: 'Period End', type: 'date', required: true },
        { key: 'total_regular_hours', label: 'Regular Hours', type: 'number', defaultValue: '40' },
      ],
    },
    'review-cycle': {
      title: 'New Review Cycle', submitLabel: 'Create', icon: Star,
      fields: [
        { key: 'name', label: 'Cycle Name', type: 'text', required: true, placeholder: 'e.g. H2 2026 Review Cycle' },
        { key: 'start_date', label: 'Start Date', type: 'date', required: true },
        { key: 'end_date', label: 'End Date', type: 'date', required: true },
      ],
    },
    'performance-review': {
      title: 'Open Performance Review', submitLabel: 'Open', icon: Star,
      fields: [
        { key: 'cycle_id', label: 'Review Cycle', type: 'select', required: true, options: reviewCycles.map(c => ({ value: c.id, label: c.name })) },
        { key: 'employee_id', label: 'Employee', type: 'select', required: true, options: employeeOptions },
        { key: 'reviewer_id', label: 'Reviewer', type: 'select', required: true, options: employeeOptions },
      ],
    },
    'self-rating': {
      title: 'Submit Self-Assessment', submitLabel: 'Submit', icon: PenLine,
      fields: [
        { key: 'rating', label: 'Self Rating (1-5)', type: 'select', required: true, options: ['1', '2', '3', '4', '5'].map(v => ({ value: v, label: v })) },
        { key: 'assessment', label: 'Self Assessment', type: 'textarea', required: true },
      ],
    },
    'manager-rating': {
      title: 'Submit Manager Rating', submitLabel: 'Submit', icon: PenLine,
      fields: [
        { key: 'rating', label: 'Manager Rating (1-5)', type: 'select', required: true, options: ['1', '2', '3', '4', '5'].map(v => ({ value: v, label: v })) },
        { key: 'assessment', label: 'Manager Assessment', type: 'textarea', required: true },
      ],
    },
    'synthesize-feedback': {
      title: 'Synthesize 360 Feedback', submitLabel: 'Synthesize', icon: Sparkles,
      fields: [{ key: 'raw_feedback', label: 'Raw Feedback (one item per line)', type: 'textarea', required: true }],
    },
    'bamboohr-connect': {
      title: 'Connect BambooHR', submitLabel: 'Sync', icon: Link2,
      fields: [
        { key: 'subdomain', label: 'BambooHR Subdomain', type: 'text', required: true, placeholder: 'e.g. acme' },
        { key: 'api_key', label: 'API Key', type: 'text', required: true },
      ],
    },
  };

  const activeModal = modalCtx ? modalConfig[modalCtx.kind] : null;

  return (
    <div className={`${PAGE_PAD} space-y-6`}>
      {/* Header */}
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-[28px] font-semibold tracking-tight" style={{ letterSpacing: '-0.6px', color: colors.ink }}>Workforce</h1>
          <p className="text-[13px] mt-0.5" style={{ color: colors.inkSubtle }}>Employee lifecycle, recruiting, benefits, compensation, payroll, and compliance in one governed workspace</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => setCreateOpen(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-semibold text-white"
            style={{ background: colors.primary }}>
            <Plus className="w-3.5 h-3.5" /> New Time-Off Request
          </button>
          <button onClick={loadData} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-medium transition-all"
            style={{ background: colors.surface1, color: colors.inkSubtle, border: `1px solid ${colors.hairline}` }}>
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>
        <CreateEntityModal open={createOpen} onClose={() => setCreateOpen(false)}
          title="New Time-Off Request" domain="hr" entityPath="time-off-requests"
          fields={[
            { key: 'employee_id', label: 'Employee', type: 'select', required: true, options: employeeOptions },
            { key: 'leave_type', label: 'Leave Type', type: 'select', defaultValue: 'PTO',
              options: ['PTO', 'SICK', 'MATERNITY', 'PATERNITY', 'BEREAVEMENT', 'JURY_DUTY', 'UNPAID'] },
            { key: 'start_date', label: 'Start Date', type: 'date', required: true },
            { key: 'end_date', label: 'End Date', type: 'date', required: true },
            { key: 'hours_requested', label: 'Hours Requested', type: 'number', required: true, defaultValue: 40 },
            { key: 'reason', label: 'Reason', type: 'textarea' },
          ]}
          onCreated={async (m) => { setActionMsg(m); await loadData(); }} />

        <CreateEntityModal open={createKind === 'requisition'} onClose={() => setCreateKind(null)}
          title="New Requisition" domain="hr" entityPath="requisitions"
          fields={[
            { key: 'title', label: 'Job Title', type: 'text', required: true },
            { key: 'department', label: 'Department', type: 'text', required: true },
            { key: 'hiring_manager_id', label: 'Hiring Manager', type: 'select', required: true, options: employeeOptions },
            { key: 'job_description', label: 'Job Description', type: 'textarea', required: true },
            { key: 'headcount', label: 'Headcount', type: 'number', defaultValue: 1 },
            { key: 'target_salary_min', label: 'Target Salary Min', type: 'number' },
            { key: 'target_salary_max', label: 'Target Salary Max', type: 'number' },
          ]}
          onCreated={async (m) => { setActionMsg(m); await loadData(); }} />

        <CreateEntityModal open={createKind === 'candidate'} onClose={() => setCreateKind(null)}
          title="Add Candidate" domain="hr" entityPath="candidates"
          fields={[
            { key: 'requisition_id', label: 'Requisition', type: 'select', required: true, options: requisitions.map(r => ({ value: r.id, label: r.title })) },
            { key: 'first_name', label: 'First Name', type: 'text', required: true },
            { key: 'last_name', label: 'Last Name', type: 'text', required: true },
            { key: 'email', label: 'Email', type: 'text', required: true },
            { key: 'phone', label: 'Phone', type: 'text' },
          ]}
          onCreated={async (m) => { setActionMsg(m); await loadData(); }} />

        {activeModal && (
          <QuickModal open={!!modalCtx} title={activeModal.title} submitLabel={activeModal.submitLabel}
            icon={activeModal.icon} fields={activeModal.fields} onClose={closeModal} onSubmit={handleModalSubmit} />
        )}
      </div>

      {/* Tab Selector */}
      <div className="flex gap-1 p-1 rounded-lg w-full max-w-full overflow-x-auto" role="tablist" aria-label="Workforce sections"
        style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
        {TABS.map(({ id, label, icon: Icon }, i) => (
          <button key={id} onClick={() => setTab(id)}
            id={`hr-tab-${id}`}
            role="tab"
            aria-selected={tab === id}
            tabIndex={tab === id ? 0 : -1}
            onKeyDown={e => {
              if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
              e.preventDefault();
              const next = TABS[(i + (e.key === 'ArrowRight' ? 1 : -1) + TABS.length) % TABS.length];
              setTab(next.id);
              document.getElementById(`hr-tab-${next.id}`)?.focus();
            }}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[12.5px] font-medium transition-all shrink-0 whitespace-nowrap"
            style={{
              background: tab === id ? colors.primary : 'transparent',
              color: tab === id ? '#fff' : colors.inkSubtle
            }}>
            <Icon className="w-3.5 h-3.5" />{label}
          </button>
        ))}
      </div>

      {/* Action feedback */}
      {actionMsg && tab !== 'recruiting' && (
        <div className="px-4 py-2.5 rounded-lg text-[12px] font-medium flex items-center gap-2"
          style={{ background: actionMsg.toLowerCase().includes('fail') ? colors.error + '15' : colors.success + '15',
                   color: actionMsg.toLowerCase().includes('fail') ? colors.error : colors.success }}>
          {actionMsg.toLowerCase().includes('fail') ? <XCircle className="w-4 h-4" /> : <CheckCircle2 className="w-4 h-4" />}
          {actionMsg}
          <button onClick={() => setActionMsg('')} className="ml-auto text-[11px] opacity-60 hover:opacity-100">dismiss</button>
        </div>
      )}

      {/* Loading State */}
      {loading ? (
        <div className="flex items-center justify-center py-20">
          <div className="flex flex-col items-center gap-3">
            <div className="w-5 h-5 border-2 rounded-full animate-spin" style={{ borderColor: colors.primary, borderTopColor: 'transparent' }} />
            <span className="text-[13px]" style={{ color: colors.inkSubtle }}>Loading workforce data…</span>
          </div>
        </div>
      ) : (
        <>
          {tab === 'directory' && renderDirectoryTab()}
          {tab === 'recruiting' && renderRecruitingTab()}
          {tab === 'time' && renderTimeTab()}
          {tab === 'performance' && renderPerformanceTab()}
          {tab === 'benefits' && renderBenefitsTab()}
          {tab === 'compensation' && renderCompensationTab()}
          {tab === 'onboarding' && renderOnboardingTab()}
          {tab === 'learning' && renderLearningTab()}
          {tab === 'er' && renderERTab()}
          {tab === 'payroll' && renderPayrollTab()}
          {tab === 'planning' && renderPlanningTab()}
          {tab === 'compliance' && renderComplianceTab()}
          {tab === 'analytics' && (
            <div className="space-y-4">
              {hrMetrics.length > 0 && (
                <div className="rounded-xl p-5" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
                  <div className="flex items-center justify-between mb-3">
                    <span className="text-[12px] font-semibold uppercase tracking-wide" style={{ color: colors.inkSubtle }}>Headcount Trend (HR Metric Snapshots)</span>
                    <ActionButton onClick={() => runAction('hr-snapshot-2', () => hrApi.generateHRMetricSnapshot(), () => 'Snapshot taken.')} busy={busyId === 'hr-snapshot-2'} icon={LineChart} label="Take Snapshot" />
                  </div>
                  <MiniDonut items={[
                    { label: 'Headcount', value: hrMetrics[hrMetrics.length - 1]?.total_headcount || 0 },
                    { label: 'Contractors', value: hrMetrics[hrMetrics.length - 1]?.active_contractors || 0 },
                  ]} size={72} centerLabel="latest" />
                </div>
              )}
              <DomainAnalytics domain="hr" />
            </div>
          )}
        </>
      )}
    </div>
  );
};

export default WorkforceView;
