import React, { useEffect, useState } from 'react';
import {
  Users, Briefcase, Calendar, Star, Search, UserPlus, Clock,
  CheckCircle2, XCircle, ArrowUpRight, BarChart3,
  MapPin, TrendingUp, RefreshCw,
  Zap, ExternalLink, ShieldAlert, Loader2
} from 'lucide-react';
import { api } from '../api/client';
import type { WorkflowSpec } from '../api/client';
import { useTheme } from '../context/ThemeContext';
import DomainAnalytics from '../components/DomainAnalytics';
import WorkflowActions from '../components/WorkflowActions';
import CreateEntityModal from '../components/CreateEntityModal';
import { Plus as PlusIcon } from 'lucide-react';

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

type HRTab = 'directory' | 'recruiting' | 'time' | 'performance' | 'analytics';

const WorkforceView: React.FC<{ domain?: string; defaultTab?: string }> = ({ defaultTab }) => {
  const { colors } = useTheme();
  const [tab, setTab] = useState<HRTab>(() => {
    const validTabs: HRTab[] = ['directory', 'recruiting', 'time', 'performance', 'analytics'];
    if (defaultTab && validTabs.includes(defaultTab as HRTab)) return defaultTab as HRTab;
    if (defaultTab === 'employees') return 'directory';
    return 'directory';
  });
  const [loading, setLoading] = useState(true);

  // Data state
  const [employees, setEmployees] = useState<HREmployee[]>([]);
  const [requisitions, setRequisitions] = useState<HRRequisition[]>([]);
  const [candidates, setCandidates] = useState<HRCandidate[]>([]);
  const [timeOff, setTimeOff] = useState<HRTimeOffRequest[]>([]);
  const [reviews, setReviews] = useState<HRPerformanceReview[]>([]);
  const [workflows, setWorkflows] = useState<Record<string, WorkflowSpec>>({});
  const [createOpen, setCreateOpen] = useState(false);

  // Filters
  const [searchQ, setSearchQ] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');

  // Recruiting action state (gated screening + stage advance)
  const [screeningId, setScreeningId] = useState<string | null>(null);
  const [advancingId, setAdvancingId] = useState<string | null>(null);
  const [provenance, setProvenance] = useState<Record<string, string>>({});
  const [actionMsg, setActionMsg] = useState<string>('');

  // Backend CandidateStage enum forward order (matches app/hr/models/recruiting.py)
  const CANDIDATE_STAGES = [
    'APPLIED', 'AI_SCREENING', 'RECRUITER_SCREEN', 'HM_INTERVIEW',
    'PANEL_INTERVIEW', 'OFFER_PREP', 'OFFER_EXTENDED', 'HIRED',
  ];

  const nextStage = (stage: string): string | null => {
    const i = CANDIDATE_STAGES.indexOf(stage);
    return i >= 0 && i < CANDIDATE_STAGES.length - 1 ? CANDIDATE_STAGES[i + 1] : null;
  };

  // Load data from all domain endpoints
   
  const loadData = async () => {
    setLoading(true);
    const [emp, req, cand, tor, rev, wf] = await Promise.allSettled([
      api.getHREmployees(),
      api.getHRRequisitions(),
      api.getHRCandidates(),
      api.getHRTimeOffRequests(),
      api.getHRPerformanceReviews(),
      api.getDomainWorkflows('hr'),
    ]);
    if (emp.status === 'fulfilled') setEmployees(emp.value || []);
    if (req.status === 'fulfilled') setRequisitions(req.value || []);
    if (cand.status === 'fulfilled') setCandidates(cand.value || []);
    if (tor.status === 'fulfilled') setTimeOff(tor.value || []);
    if (rev.status === 'fulfilled') setReviews(rev.value || []);
    if (wf.status === 'fulfilled') setWorkflows(wf.value || {});
    setLoading(false);
  };

  const handleScreen = async (candidateId: string) => {
    setScreeningId(candidateId);
    setActionMsg('');
    try {
      const res = await api.screenHRCandidate(candidateId);
      const execId = res?.provenance?.execution_id;
      if (execId) setProvenance(prev => ({ ...prev, [candidateId]: execId }));
      if (res?.screening === 'gated') {
        setActionMsg(`Screening gated (${res.status}) - routed for human review.`);
      } else {
        setActionMsg('AI screening complete.');
      }
      await loadData();
    } catch (e: any) {
      setActionMsg(`Screening failed: ${e?.message || e}`);
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

  useEffect(() => {
    loadData();
  }, []);

  // ── Status color helper ──
  const statusColor = (s: string) => {
    const normalized = (s || '').toUpperCase();
    if (['ACTIVE', 'APPROVED', 'COMPLETED', 'HIRED', 'FILLED'].includes(normalized)) return colors.success;
    if (['PENDING', 'REQUESTED', 'DRAFT', 'ONBOARDING', 'IN_PROGRESS', 'PENDING_APPROVAL'].includes(normalized)) return colors.warning;
    if (['REJECTED', 'DENIED', 'TERMINATED', 'CANCELLED', 'FAILED'].includes(normalized)) return colors.error;
    if (['OPEN', 'APPLIED', 'AI_SCREENING', 'RECRUITER_SCREEN'].includes(normalized)) return colors.info;
    return colors.inkSubtle;
  };

  // ── Metric Cards ──
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

  // ── Status Badge ──
  const Badge = ({ status }: { status: string }) => (
    <span className="text-[10px] font-medium px-2 py-0.5 rounded-full uppercase tracking-wide"
      style={{ background: statusColor(status) + '18', color: statusColor(status) }}>
      {(status || 'UNKNOWN').replace(/_/g, ' ')}
    </span>
  );

  // ── Empty State ──
  const EmptyState = ({ icon: Icon, title, sub }: { icon: React.ElementType; title: string; sub: string }) => (
    <div className="rounded-xl p-16 text-center" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
      <Icon className="w-12 h-12 mx-auto mb-4" style={{ color: colors.inkTertiary }} />
      <p className="text-[15px] font-medium" style={{ color: colors.inkSubtle }}>{title}</p>
      <p className="text-[12px] mt-1" style={{ color: colors.inkTertiary }}>{sub}</p>
    </div>
  );

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
        {/* KPI Row */}
        <div className="grid grid-cols-4 gap-4">
          <MetricCard label="Total Headcount" value={employees.length} icon={Users} />
          <MetricCard label="Active" value={employees.filter(e => (e.status || '').toUpperCase() === 'ACTIVE').length} icon={CheckCircle2} accent={colors.success} />
          <MetricCard label="Onboarding" value={employees.filter(e => (e.status || '').toUpperCase() === 'ONBOARDING').length} icon={UserPlus} accent={colors.info} />
          <MetricCard label="On Leave" value={employees.filter(e => (e.status || '').toUpperCase() === 'LEAVE').length} icon={Calendar} accent={colors.warning} />
        </div>

        {/* Search + Filter */}
        <div className="flex gap-3 items-center">
          <div className="relative flex-1">
            <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4" style={{ color: colors.inkTertiary }} />
            <input value={searchQ} onChange={e => setSearchQ(e.target.value)}
              placeholder="Search employees by name or email…"
              className="w-full pl-10 pr-4 py-2.5 rounded-lg text-[13px] outline-none transition-all"
              style={{ background: colors.surface1, border: `1px solid ${colors.hairline}`, color: colors.ink }}
              onFocus={e => (e.target.style.borderColor = colors.primary)}
              onBlur={e => (e.target.style.borderColor = colors.hairline)} />
          </div>
          <div className="flex gap-1.5">
            <button onClick={() => setStatusFilter('all')}
              className="px-3 py-1.5 rounded-full text-[11px] font-medium transition-all"
              style={{
                background: statusFilter === 'all' ? colors.primary : colors.surface1,
                color: statusFilter === 'all' ? '#fff' : colors.inkSubtle,
                border: `1px solid ${statusFilter === 'all' ? colors.primary : colors.hairline}`
              }}>All</button>
            {statuses.map(s => (
              <button key={s} onClick={() => setStatusFilter(s)}
                className="px-3 py-1.5 rounded-full text-[11px] font-medium transition-all capitalize"
                style={{
                  background: statusFilter === s ? colors.primary : colors.surface1,
                  color: statusFilter === s ? '#fff' : colors.inkSubtle,
                  border: `1px solid ${statusFilter === s ? colors.primary : colors.hairline}`
                }}>{s.toLowerCase()}</button>
            ))}
          </div>
        </div>

        {/* Table */}
        {filtered.length === 0 ? (
          <EmptyState icon={Users} title="No employees found" sub={employees.length === 0 ? "Connect an HRIS (e.g., BambooHR) to sync employee data" : "Try adjusting your search or filters"} />
        ) : (
          <div className="rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
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
                        <span className="text-[12px]" style={{ color: colors.inkMuted }}>{emp.location || 'Remote'}</span>
                      </div>
                    </td>
                    <td className="px-5 py-3"><Badge status={emp.status} /></td>
                    <td className="px-5 py-3 text-[12px]" style={{ color: colors.inkTertiary }}>{emp.hire_date || '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
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
        {/* KPI Row */}
        <div className="grid grid-cols-4 gap-4">
          <MetricCard label="Open Requisitions" value={requisitions.filter(r => r.status === 'OPEN').length} icon={Briefcase} />
          <MetricCard label="Active Candidates" value={candidates.filter(c => !['HIRED', 'REJECTED', 'WITHDRAWN'].includes(c.stage)).length} icon={UserPlus} accent={colors.info} />
          <MetricCard label="Avg AI Score" value={candidates.length > 0 ? Math.round(candidates.reduce((a, c) => a + (c.ai_score || 0), 0) / Math.max(candidates.length, 1)) : '-'} icon={Star} accent={colors.warning} />
          <MetricCard label="Hired This Period" value={candidates.filter(c => c.stage === 'HIRED').length} icon={CheckCircle2} accent={colors.success} />
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
            <div className="p-10 text-center text-[13px]" style={{ color: colors.inkTertiary }}>No requisitions yet. Create one from the HR backend.</div>
          ) : (
            requisitions.map((req, i) => (
              <div key={req.id} className="px-5 py-3 flex items-center justify-between transition-colors"
                style={{ borderTop: i > 0 ? `1px solid ${colors.hairline}` : undefined }}
                onMouseEnter={e => (e.currentTarget.style.background = colors.surface2)}
                onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}>
                <div className="flex-1">
                  <span className="text-[13px] font-medium" style={{ color: colors.ink }}>{req.title}</span>
                  <div className="flex items-center gap-3 mt-1">
                    <span className="text-[11px]" style={{ color: colors.inkSubtle }}>{req.department || 'Engineering'}</span>
                    {req.headcount && <span className="text-[11px]" style={{ color: colors.inkTertiary }}>{req.headcount} headcount</span>}
                    {req.target_salary_min && req.target_salary_max && (
                      <span className="text-[11px]" style={{ color: colors.inkTertiary }}>${(req.target_salary_min / 1000).toFixed(0)}k - ${(req.target_salary_max / 1000).toFixed(0)}k</span>
                    )}
                  </div>
                </div>
                <Badge status={req.status} />
              </div>
            ))
          )}
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
                        {stageLabels[stage] || stage}
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
                              <p className="text-[10px] mt-1 line-clamp-2" style={{ color: colors.inkSubtle }}>{c.ai_summary}</p>
                            )}
                            {(c.ai_red_flags || []).length > 0 && (
                              <div className="mt-1.5 space-y-0.5">
                                {(c.ai_red_flags || []).slice(0, 3).map((f, idx) => (
                                  <div key={idx} className="flex items-start gap-1 text-[10px]" style={{ color: colors.error }}>
                                    <ShieldAlert className="w-3 h-3 flex-shrink-0 mt-0.5" />
                                    <span className="line-clamp-1">{f}</span>
                                  </div>
                                ))}
                              </div>
                            )}
                            {execId && (
                              <a href={`/platform/decisions?execution_id=${execId}`}
                                className="mt-1.5 flex items-center gap-1 text-[10px]" style={{ color: colors.primary }}>
                                <ExternalLink className="w-3 h-3" /> Provenance {execId.slice(0, 8)}…
                              </a>
                            )}
                            {/* Actions */}
                            <div className="mt-2 flex items-center gap-1.5">
                              <button
                                onClick={() => handleScreen(c.id)}
                                disabled={screeningId === c.id}
                                className="flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium disabled:opacity-50"
                                style={{ background: colors.primary + '15', color: colors.primary }}>
                                {screeningId === c.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Zap className="w-3 h-3" />}
                                Screen
                              </button>
                              {next && (
                                <button
                                  onClick={() => handleAdvance(c.id, next)}
                                  disabled={advancingId === c.id}
                                  className="flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium disabled:opacity-50"
                                  style={{ background: colors.surface2, color: colors.inkSubtle }}>
                                  {advancingId === c.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <ArrowUpRight className="w-3 h-3" />}
                                  Advance
                                </button>
                              )}
                            </div>
                          </div>
                        );
                      })}
                      {inStage.length === 0 && (
                        <div className="text-[10px] text-center py-3 rounded-lg border border-dashed"
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
      <div className="grid grid-cols-4 gap-4">
        <MetricCard label="Total Requests" value={timeOff.length} icon={Calendar} />
        <MetricCard label="Pending" value={timeOff.filter(t => t.status === 'REQUESTED').length} icon={Clock} accent={colors.warning} />
        <MetricCard label="Approved" value={timeOff.filter(t => t.status === 'APPROVED').length} icon={CheckCircle2} accent={colors.success} />
        <MetricCard label="Denied" value={timeOff.filter(t => t.status === 'DENIED').length} icon={XCircle} accent={colors.error} />
      </div>

      <div className="rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
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
                {['Employee ID', 'Type', 'Start', 'End', 'Hours', 'Status', 'Actions'].map(h => (
                  <th key={h} className="text-left text-[11px] font-semibold uppercase tracking-wider px-5 py-2.5" style={{ color: colors.inkSubtle }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {timeOff.map((t, i) => (
                <tr key={t.id} style={{ borderTop: i > 0 ? `1px solid ${colors.hairline}` : undefined }}>
                  <td className="px-5 py-3 text-[12px] font-mono" style={{ color: colors.inkMuted }}>{t.employee_id.slice(0, 8)}…</td>
                  <td className="px-5 py-3">
                    <span className="text-[11px] font-medium px-2 py-0.5 rounded-full" style={{ background: colors.surface2, color: colors.inkSubtle }}>{(t.leave_type || 'PTO').replace(/_/g, ' ')}</span>
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
        <div className="grid grid-cols-4 gap-4">
          <MetricCard label="Total Reviews" value={reviews.length} icon={Star} />
          <MetricCard label="Completed" value={reviews.filter(r => r.status === 'COMPLETED').length} icon={CheckCircle2} accent={colors.success} />
          <MetricCard label="In Progress" value={reviews.filter(r => ['DRAFT', 'PENDING_EMPLOYEE', 'PENDING_MANAGER'].includes(r.status)).length} icon={Clock} accent={colors.warning} />
          <MetricCard label="Avg Rating" value={reviews.length > 0 ? (reviews.reduce((a, r) => a + (r.manager_rating || 0), 0) / Math.max(reviews.filter(r => r.manager_rating != null).length, 1)).toFixed(1) : '-'} icon={TrendingUp} accent={colors.info} />
        </div>

        <div className="rounded-xl overflow-hidden" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
          <div className="px-5 py-3 flex items-center gap-2" style={{ borderBottom: `1px solid ${colors.hairline}` }}>
            <Star className="w-4 h-4" style={{ color: colors.primary }} />
            <span className="text-[14px] font-medium" style={{ color: colors.ink }}>Performance Reviews</span>
          </div>
          {reviews.length === 0 ? (
            <div className="p-10 text-center text-[13px]" style={{ color: colors.inkTertiary }}>No performance reviews yet. Initiate a review cycle from the backend.</div>
          ) : (
            <table className="w-full">
              <thead>
                <tr style={{ background: colors.surface2 }}>
                  {['Employee', 'Self Rating', 'Manager Rating', 'Status'].map(h => (
                    <th key={h} className="text-left text-[11px] font-semibold uppercase tracking-wider px-5 py-2.5" style={{ color: colors.inkSubtle }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {reviews.map((rev, i) => (
                  <tr key={rev.id} style={{ borderTop: i > 0 ? `1px solid ${colors.hairline}` : undefined }}>
                    <td className="px-5 py-3 text-[12px] font-mono" style={{ color: colors.inkMuted }}>{rev.employee_id.slice(0, 8)}…</td>
                    <td className="px-5 py-3">
                      {rev.self_rating != null ? (
                        <div className="flex items-center gap-1.5">
                          <span className="text-[14px] font-bold" style={{ color: ratingColor(rev.self_rating) }}>{rev.self_rating}</span>
                          <span className="text-[10px]" style={{ color: colors.inkTertiary }}>/ 5</span>
                        </div>
                      ) : <span className="text-[11px]" style={{ color: colors.inkTertiary }}>Pending</span>}
                    </td>
                    <td className="px-5 py-3">
                      {rev.manager_rating != null ? (
                        <div className="flex items-center gap-1.5">
                          <span className="text-[14px] font-bold" style={{ color: ratingColor(rev.manager_rating) }}>{rev.manager_rating}</span>
                          <span className="text-[10px]" style={{ color: colors.inkTertiary }}>/ 5</span>
                        </div>
                      ) : <span className="text-[11px]" style={{ color: colors.inkTertiary }}>Pending</span>}
                    </td>
                    <td className="px-5 py-3"><Badge status={rev.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
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
    { id: 'analytics', label: 'Analytics', icon: BarChart3 },
  ];

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-[28px] font-semibold tracking-tight" style={{ letterSpacing: '-0.6px', color: colors.ink }}>Workforce</h1>
          <p className="text-[13px] mt-0.5" style={{ color: colors.inkSubtle }}>Employee directory, recruiting pipeline, time tracking, and performance management</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => setCreateOpen(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-semibold text-white"
            style={{ background: colors.primary }}>
            <PlusIcon className="w-3.5 h-3.5" /> New Time-Off Request
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
            { key: 'employee_id', label: 'Employee', type: 'select', required: true,
              options: employees.map(e => ({ value: e.id, label: `${e.first_name} ${e.last_name}` })) },
            { key: 'leave_type', label: 'Leave Type', type: 'select', defaultValue: 'PTO',
              options: ['PTO', 'SICK', 'MATERNITY', 'PATERNITY', 'BEREAVEMENT', 'JURY_DUTY', 'UNPAID'] },
            { key: 'start_date', label: 'Start Date', type: 'date', required: true },
            { key: 'end_date', label: 'End Date', type: 'date', required: true },
            { key: 'hours_requested', label: 'Hours Requested', type: 'number', required: true, defaultValue: 40 },
            { key: 'reason', label: 'Reason', type: 'textarea' },
          ]}
          onCreated={async (m) => { setActionMsg(m); await loadData(); }} />
      </div>

      {/* Tab Selector */}
      <div className="flex gap-1 p-1 rounded-lg w-fit" style={{ background: colors.surface1, border: `1px solid ${colors.hairline}` }}>
        {TABS.map(({ id, label, icon: Icon }) => (
          <button key={id} onClick={() => setTab(id)}
            className="flex items-center gap-1.5 px-4 py-1.5 rounded-md text-[13px] font-medium transition-all"
            style={{
              background: tab === id ? colors.primary : 'transparent',
              color: tab === id ? '#fff' : colors.inkSubtle
            }}>
            <Icon className="w-3.5 h-3.5" />{label}
          </button>
        ))}
      </div>

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
          {tab === 'analytics' && <DomainAnalytics domain="hr" />}
        </>
      )}
    </div>
  );
};

export default WorkforceView;
